from datetime import date, datetime

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.addons.resource.models.utils import HOURS_PER_DAY

import logging
_logger = logging.getLogger(__name__)

# Odoo 20 replaced hr.leave.type by hr.work.entry.type and removed the xmlid hr_holidays.leave_type_paid_time_off:
# paid time off is any time type with the legal leave code (one per country).
PAID_TIME_OFF_CODE = '016.00'
# Odoo 20 replaced request_unit_half by request_duration ('am'/'pm' = half day)
HALF_DAY_DURATIONS = ('am', 'pm')
# Values the Odoo 20 form may leave out of `vals` (field default or `default_*` context instead)
CREATE_DEFAULT_FIELDS = ['employee_id', 'work_entry_type_id', 'request_date_from', 'request_date_to',
                         'request_duration']


class BHSHrLeave(models.Model):
    _inherit = 'hr.leave'

    @api.constrains(
        'request_date_from',
        'request_date_to',
        'employee_id',
        'work_entry_type_id',
        'state'
    )
    def _check_leave_within_allocation_period(self):
        """Leave dates must be covered by ONE validated allocation (no cross-year use of an allocation).

        Runs before core _check_validity, so this message is the one shown.
        """
        # Core bypass keys are honoured only for trusted callers: any RPC client can set them. Constraints run
        # in sudo but env.user is still the caller. Batch wizard: Time Off Responsible; plain bypass: officers.
        context = self.env.context
        user = self.env.user
        trusted_batch = context.get('multi_leave_request') and (
            user._is_superuser() or user.has_group('hr_holidays.group_hr_holidays_responsible'))
        trusted_skip = context.get('skip_allocation_check') and (
            user._is_superuser() or user.has_group('hr_holidays.group_hr_holidays_user'))
        if trusted_batch or trusted_skip:
            return
        for leave in self:
            if leave.state not in ('confirm', 'validate', 'validate1'):
                continue

            if not leave.employee_id or not leave.work_entry_type_id:
                continue

            if not leave.work_entry_type_id.requires_allocation:
                continue

            if not leave.request_date_from or not leave.request_date_to:
                continue

            # record rules must not hide the allocation (false refusal)
            allocation = self.env['hr.leave.allocation'].sudo().search([
                ('employee_id', '=', leave.employee_id.id),
                ('work_entry_type_id', '=', leave.work_entry_type_id.id),
                ('state', '=', 'validate'),
                ('date_from', '<=', leave.request_date_from),
                '|',
                ('date_to', '=', False),
                ('date_to', '>=', leave.request_date_to),
            ], limit=1)

            if not allocation:
                raise ValidationError(_(
                    "You do not have a valid leave allocation covering the selected dates.\n"
                    "Please request an allocation for this period or split the leave by year."
                ))

    @api.onchange('employee_id', 'request_date_from', 'request_date_to')
    def _onchange_work_entry_type_id(self):
        """Keep the paid time off type on the form; the period constraint refuses the save instead.

        Odoo 20: the core onchange swaps a type without allocation and reads the HR-only employee country.
        """
        others = self.filtered(lambda leave: not self._hla_is_paid_time_off(leave.work_entry_type_id))
        if others:
            return super(BHSHrLeave, others)._onchange_work_entry_type_id()
        return None

    @api.model
    def _hla_is_paid_time_off(self, work_entry_type):
        return work_entry_type.code == PAID_TIME_OFF_CODE

    @api.model
    def _hla_count_leave_days(self, values, edited_leave=None):
        """Leave days of a request, as core counts them; 0.5 for a half day.

        The absences of `edited_leave` are not counted against its own new dates.
        """
        if values.get('request_duration') in HALF_DAY_DURATIONS:
            return 0.5
        # No `origin`: a new record with origin keeps the stored number_of_days of the edited leave.
        leave = self.new({**values, 'request_date_from_period': 'am', 'request_date_to_period': 'pm'})
        domain = [('holiday_id', '!=', edited_leave.id)] if edited_leave else None
        days, _hours = leave._get_durations(additional_domain=domain).get(leave.id, (0, 0))
        return days

    @api.model
    def _hla_remaining_leaves(self, employee, work_entry_type):
        """Remaining days of one type on the allocations valid today (core figure adds up every type)."""
        if not employee:
            # core would fall back to the employee of the calling user
            return 0.0
        today = date.today()  # as core _compute_allocation_remaining_display
        consumed = employee._get_consumed_leaves(work_entry_type)[0][employee][work_entry_type]
        unit = 'hours' if work_entry_type.unit_of_measure == 'hour' else 'days'
        remaining = 0.0
        for allocation, data in consumed.items():
            if not allocation or allocation.date_from > today or (allocation.date_to and allocation.date_to < today):
                continue
            if unit == 'days':
                remaining += data['days_virtual_remaining_leaves']
            else:
                remaining += data['hours_virtual_remaining_leaves'] / (
                    employee.resource_calendar_id.hours_per_day or HOURS_PER_DAY)
        return remaining

    @api.model
    def _hla_exceeds_monthly_accrual(self, employee, work_entry_type, leave_allocation, leave_days):
        """True when the paid leave used this year (with the new days) exceeds the months worked this year."""
        current_month = datetime.now().month
        current_year = datetime.now().year
        allocations = self.env['hr.leave.allocation'].sudo().search([
            ('employee_id', '=', employee.id),
            ('date_from', '>=', datetime(current_year, 1, 1)),
            ('date_from', '<=', datetime(current_year, 12, 31)),
            '|',
            ('date_to', '=', False),
            ('date_to', '<=', datetime(current_year, 12, 31)),
            ('work_entry_type_id', '=', work_entry_type.id),
            ('state', '=', 'validate'),
        ])
        if not allocations:
            return False
        # several allocations in the year: all allocated days, months counted from the earliest start
        allocated_days = sum(allocations.mapped('number_of_days_display'))
        first_month = min(allocations.mapped('date_from')).month
        total_used_leave_allocation = (allocated_days - leave_allocation) + leave_days
        return total_used_leave_allocation > (current_month - first_month + 1)

    def _hla_send_alert(self):
        """Post the warning by OdooBot on each leave and show a sticky notification to the acting user."""
        body = _(
            "You have used more annual leave days than the number of months you have worked this year. These leave days may be revoked if you leave your job.")
        odoobot_user = self.env.ref('base.user_root')
        for record in self:
            record.with_user(odoobot_user).message_post(body=body)
        if self:
            # one notification for the whole batch
            self.env.user._bus_send('simple_notification', {
                "type": "warning",
                "title": _("Time Off Notification"),
                "message": body,
                "sticky": True,
            })

    @api.model_create_multi
    def create(self, vals_list):
        # index in vals_list -> (employee, type, dates) of requests above the accrual
        alerts = {}
        for index, values in enumerate(vals_list):
            missing = [field for field in CREATE_DEFAULT_FIELDS if field not in values]
            if missing:
                # same defaults as the ORM will store
                values = {**self.default_get(missing), **values}
            employee = self.env['hr.employee'].browse(values.get('employee_id'))
            leave_type = self.env['hr.work.entry.type'].browse(values.get('work_entry_type_id'))
            if not self._hla_is_paid_time_off(leave_type):
                continue
            date_from = fields.Date.to_date(values.get('request_date_from'))
            date_to = fields.Date.to_date(values.get('request_date_to'))
            if not date_from or not date_to:
                continue
            leave_allocation = self._hla_remaining_leaves(employee, leave_type)
            leave_days = self._hla_count_leave_days({
                'employee_id': employee.id,
                'work_entry_type_id': leave_type.id,
                'request_date_from': date_from,
                'request_date_to': date_to,
                'request_duration': values.get('request_duration'),
            })
            if leave_allocation < leave_days:
                raise UserError(_('Not enough annual leave'))
            if self._hla_exceeds_monthly_accrual(employee, leave_type, leave_allocation, leave_days):
                alerts[index] = (employee.id, leave_type.id, date_from, date_to)

        res = super(BHSHrLeave, self).create(vals_list)
        if alerts:
            if len(res) == len(vals_list):
                flagged = self.browse([res[index].id for index in alerts])
            else:
                # Odoo 20 drops invalid leaves of a multi-create: match the flagged ones by employee, type, dates
                keys = set(alerts.values())
                flagged = res.filtered(lambda leave: (
                    leave.employee_id.id, leave.work_entry_type_id.id,
                    leave.request_date_from, leave.request_date_to) in keys)
            flagged._hla_send_alert()
        return res

    def write(self, values):
        check = False
        if values.get('request_date_from') or values.get('request_date_to'):
            for record in self:
                if not self._hla_is_paid_time_off(record.work_entry_type_id):
                    continue
                leave_allocation = self._hla_remaining_leaves(record.employee_id, record.work_entry_type_id)
                if values.get('request_date_from'):
                    current_day = fields.Date.to_date(values.get('request_date_from'))
                else:
                    current_day = record.request_date_from
                if values.get('request_date_to'):
                    date_to = fields.Date.to_date(values.get('request_date_to'))
                else:
                    date_to = record.request_date_to
                # the days of the leave being edited are given back before the check
                leave_allocation += record.number_of_days
                leave_days = self._hla_count_leave_days({
                    'employee_id': record.employee_id.id,
                    'work_entry_type_id': record.work_entry_type_id.id,
                    'request_date_from': current_day,
                    'request_date_to': date_to,
                    'request_duration': values.get('request_duration', record.request_duration),
                }, edited_leave=record)
                if leave_allocation < leave_days:
                    raise UserError(_('Not enough annual leave'))
                if self._hla_exceeds_monthly_accrual(
                        record.employee_id, record.work_entry_type_id, leave_allocation, leave_days):
                    check = True
        res = super(BHSHrLeave, self).write(values)
        if check:
            self._hla_send_alert()
        return res
