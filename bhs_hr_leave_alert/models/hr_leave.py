from odoo import models, fields, api, _
from datetime import timedelta, datetime
from odoo.exceptions import UserError, ValidationError

import logging
_logger = logging.getLogger(__name__)


class BHSHrLeave(models.Model):
    _inherit = 'hr.leave'

    @api.constrains(
        'request_date_from',
        'request_date_to',
        'employee_id',
        'holiday_status_id',
        'state'
    )
    def _check_leave_within_allocation_period(self):
        """
        Ensure leave dates are fully covered by ONE validated allocation.
        This prevents:
        - Using previous year allocation for next year leave
        - Incorrect allocation consumption
        """
        for leave in self:
            # Only check when approving
            if leave.state not in ('confirm', 'validate', 'validate1'):
                continue

            if not leave.employee_id or not leave.holiday_status_id:
                continue

            if leave.holiday_status_id.requires_allocation != 'yes':
                continue

            if not leave.request_date_from or not leave.request_date_to:
                continue

            allocation = self.env['hr.leave.allocation'].search([
                ('employee_id', '=', leave.employee_id.id),
                ('holiday_status_id', '=', leave.holiday_status_id.id),
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

    @api.model_create_multi
    def create(self, vals_list):
        check = False
        for values in vals_list:
            employee_id = values.get('employee_id')
            employee = self.env['hr.employee'].browse(employee_id)
            user = employee.user_id
            leave_type_id = values.get('holiday_status_id')
            leave_type = self.env['hr.leave.type'].browse(leave_type_id)
            time_off_type = self.env.ref('hr_holidays.holiday_status_cl')
            if leave_type.id == time_off_type.id:
                leave_allocation = float(
                    user.allocation_remaining_display) if user.allocation_remaining_display else 0.0
                unit_half = values.get('request_unit_half')
                date_from_str = values.get('request_date_from')
                date_to_str = values.get('request_date_to')
                current_day = datetime.strptime(date_from_str, '%Y-%m-%d') if isinstance(date_from_str,
                                                                                         str) else date_from_str
                date_to = datetime.strptime(date_to_str, '%Y-%m-%d') if isinstance(date_to_str, str) else date_to_str
                if unit_half:
                    leave_days = 0.5
                else:
                    leave_days = 0.0
                    while current_day <= date_to:
                        if current_day.weekday() < 5:
                            leave_days += 1
                        current_day = current_day + timedelta(days=1)
                #Kiểm tra xem còn đủ số phép năm để tạo đơn không
                if leave_allocation < leave_days:
                    raise UserError(_('Not enough annual leave'))
                else:
                    #Kiểm tra số phép sử dụng đã vượt quá số tháng trong năm chưa
                    current_month = datetime.now().month
                    current_year = datetime.now().year
                    leave_allocation_record = self.env['hr.leave.allocation'].search(
                        [('employee_id', '=', employee_id),
                         ('date_from', '>=', datetime(current_year, 1, 1)),
                         ('date_to', '<=', datetime(current_year, 12, 31)),
                         ('holiday_status_id', '=', leave_type_id),
                         ('state', '=', 'validate')
                         ]
                    )
                    if leave_allocation_record:
                        total_used_leave_allocation = (leave_allocation_record.number_of_days_display - leave_allocation) + leave_days
                        if total_used_leave_allocation > (current_month - leave_allocation_record.date_from.month + 1):
                            check = True

        res = super(BHSHrLeave, self).create(vals_list)
        if check:
            body = _(
                "You have used more annual leave days than the number of months you have worked this year. These leave days may be revoked if you leave your job.")
            odoobot_user = self.env.ref('base.user_root')
            res.with_user(odoobot_user).message_post(body=body)
            self.env['bus.bus']._sendone(
                self.env.user.partner_id,
                "simple_notification",
                {
                    "type": "warning",
                    "title": _("Time Off Notification"),
                    "message": body,
                    "sticky": True,  # Nếu là True, thông báo sẽ không tự biến mất
                },
            )
        return res

    def write(self, values):
        check = False
        for record in self:
            employee = self.env['hr.employee'].browse(record.employee_id.id)
            time_off_type = self.env.ref('hr_holidays.holiday_status_cl')
            user = employee.user_id
            if record.holiday_status_id.id == time_off_type.id and (values.get('request_date_from') or values.get('request_date_to')):
                leave_allocation = float(
                    user.allocation_remaining_display) if user.allocation_remaining_display else 0.0
                unit_half = record.request_unit_half
                if values.get('request_date_from'):
                    current_day = datetime.strptime(values.get('request_date_from').date(), '%Y-%m-%d') if isinstance(
                        values.get('request_date_from'), str) else values.get('request_date_from')
                else:
                    current_day = record.request_date_from
                if values.get('request_date_to'):
                    date_to = datetime.strptime(values.get('request_date_to'), '%Y-%m-%d').date() if isinstance(
                        values.get('request_date_to'), str) else values.get('request_date_to')
                else:
                    date_to = record.request_date_to
                leave_allocation += record.number_of_days
                if unit_half:
                    leave_days = 0.5
                else:
                    leave_days = 0.0
                    while current_day <= date_to:
                        if current_day.weekday() < 5:
                            leave_days += 1
                        current_day = current_day + timedelta(days=1)
                # Kiểm tra xem còn đủ số phép năm để tạo đơn không
                if leave_allocation < leave_days:
                    raise UserError(_('Not enough annual leave'))
                else:
                    # Kiểm tra số phép sử dụng đã vượt quá số tháng trong năm chưa
                    current_month = datetime.now().month
                    current_year = datetime.now().year
                    leave_allocation_record = self.env['hr.leave.allocation'].search(
                        [('employee_id', '=', record.employee_id.id),
                         ('date_from', '>=', datetime(current_year, 1, 1)),
                         ('date_to', '<=', datetime(current_year, 12, 31)),
                         ('holiday_status_id', '=', record.holiday_status_id.id),
                         ('state', '=', 'validate')
                         ]
                    )
                    if leave_allocation_record:
                        total_used_leave_allocation = (leave_allocation_record.number_of_days_display - leave_allocation) + leave_days
                        if total_used_leave_allocation > (current_month - leave_allocation_record.date_from.month + 1):
                            check = True
        res = super(BHSHrLeave, self).write(values)
        if check:
            body = _(
                "You have used more annual leave days than the number of months you have worked this year. These leave days may be revoked if you leave your job.")
            odoobot_user = self.env.ref('base.user_root')
            for record in self:
                record.with_user(odoobot_user).message_post(body=body)
                self.env['bus.bus']._sendone(
                    self.env.user.partner_id,
                    "simple_notification",
                    {
                        "type": "warning",
                        "title": _("Time Off Notification"),
                        "message": body,
                        "sticky": True,  # Nếu là True, thông báo sẽ không tự biến mất
                    },
                )
        return res