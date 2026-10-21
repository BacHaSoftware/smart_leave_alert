# -*- coding: utf-8 -*-
from datetime import date

from odoo.addons.bus.models.bus import channel_with_db
from odoo.addons.mail.tests.common import MockEmail
from odoo.tests import TransactionCase, new_test_user

MODULE = 'bhs_hr_leave_alert'
TZ_UI = 'Asia/Ho_Chi_Minh'
TODAY = '2026-03-10'  # Tuesday, third month of the year
YEAR_START = date(2026, 1, 1)
YEAR_END = date(2026, 12, 31)
NOT_ENOUGH = 'Not enough annual leave'
WARNING_TEXT = 'You have used more annual leave days than the number of months you have worked this year.'
WARNING_TITLE = 'Time Off Notification'

EMPLOYEE_GROUPS = 'base.group_user,hr_holidays.group_hr_holidays_employee'
OFFICER_GROUPS = 'base.group_user,hr_holidays.group_hr_holidays_user'
MANAGER_GROUPS = 'base.group_user,hr_holidays.group_hr_holidays_manager'


class LeaveAlertCase(TransactionCase, MockEmail):
    """Employees with a Mon-Fri calendar, the paid time off type (code 016.00) and a non-paid type."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'HLA 40h Mon-Fri',
            'attendance_ids': [
                (0, 0, {'dayofweek': str(day), 'hour_from': hour, 'hour_to': hour + 4})
                for day in range(5) for hour in (8, 13)
            ],
        })
        # Odoo 20: paid time off = a work entry type with code 016.00. Existing types may have leaves (frozen
        # allocation requirement), so use a fresh one for the company country (types are filtered by country).
        cls.env.company.country_id = cls.env.ref('base.vn')
        cls.paid_type = cls.env['hr.work.entry.type'].create({
            'name': 'HLA Legal leave',
            'code': '016.00',
            'country_id': cls.env.ref('base.vn').id,
            'requires_allocation': True,
            'request_unit': 'half_day',
            'unit_of_measure': 'day',
            'leave_validation_type': 'hr',
            'time_off_selectable': True,
            'employee_requests': True,
        })
        cls.other_type = cls.env['hr.work.entry.type'].create({
            'name': 'HLA Other Time Off',
            'code': 'HLA.OTHER',
            'requires_allocation': False,
            'request_unit': 'day',
            'unit_of_measure': 'day',
            'leave_validation_type': 'hr',
            'time_off_selectable': True,
        })
        cls.odoobot = cls.env.ref('base.user_root')

        cls.user_employee = cls._make_user('hla_employee', EMPLOYEE_GROUPS)
        cls.user_officer = cls._make_user('hla_officer', OFFICER_GROUPS)
        cls.user_manager = cls._make_user('hla_manager', MANAGER_GROUPS)
        cls.employee = cls._make_employee('HLA Employee', cls.user_employee)
        cls.officer_employee = cls._make_employee('HLA Officer', cls.user_officer)
        cls.manager_employee = cls._make_employee('HLA Manager', cls.user_manager)
        cls.other_user = cls._make_user('hla_other', EMPLOYEE_GROUPS)
        cls.other_employee = cls._make_employee('HLA Other Employee', cls.other_user)

    @classmethod
    def _make_user(cls, login, groups):
        return new_test_user(cls.env, login=login, groups=groups, email=f'{login}@example.com', tz='UTC')

    @classmethod
    def _make_employee(cls, name, user):
        return cls.env['hr.employee'].create({
            'name': name,
            'user_id': user.id,
            'resource_calendar_id': cls.calendar.id,
            'date_version': date(2025, 1, 1),
            'tz': 'UTC',
        })

    def setUp(self):
        super().setUp()
        self.enterContext(self.mock_mail_gateway())
        self._clear_bus()

    # ------------------------------------------------------------------ helpers

    def allocate(self, days, employee=None, date_from=YEAR_START, date_to=YEAR_END, work_entry_type=None):
        allocation = self.env['hr.leave.allocation'].create({
            'name': 'HLA allocation',
            'employee_id': (employee or self.employee).id,
            'work_entry_type_id': (work_entry_type or self.paid_type).id,
            'number_of_days': days,
            'date_from': date_from,
            'date_to': date_to,
        })
        allocation.action_approve()
        self.assertEqual(allocation.state, 'validate')
        return allocation

    def leave_vals(self, date_from, date_to, employee=None, work_entry_type=None, **extra):
        vals = {
            'employee_id': (employee or self.employee).id,
            'work_entry_type_id': (work_entry_type or self.paid_type).id,
            'request_date_from': date_from,
            'request_date_to': date_to,
        }
        vals.update(extra)
        if vals.get('request_duration') in ('am', 'pm'):
            # what the form onchange does for a half day
            vals.setdefault('request_date_from_period', vals['request_duration'])
            vals.setdefault('request_date_to_period', vals['request_duration'])
        return vals

    def take_leave(self, date_from, date_to, user=None, **extra):
        """Create a paid leave through the ORM, as `user` (default: the employee himself)."""
        return self.env['hr.leave'].with_user(user or self.user_employee).create(
            self.leave_vals(date_from, date_to, **extra))

    def remaining(self, employee=None):
        employee = (employee or self.employee).with_env(self.env)
        employee.invalidate_recordset(['allocation_remaining_display'])
        return float(employee.allocation_remaining_display)

    def _clear_bus(self):
        self.env.cr.precommit.data.get('bus.bus.values', []).clear()

    def alert_notifications(self):
        """Pending bus notifications of the module (sticky warning 'Time Off Notification')."""
        return [
            (channel, message)
            for channel, notification_type, message in self.env.cr.precommit.data.get('bus.bus.values', [])
            if notification_type == 'simple_notification' and message.get('title') == WARNING_TITLE
        ]

    def assertAlerted(self, leave, user):
        messages = leave.sudo().message_ids.filtered(lambda m: WARNING_TEXT in (m.body or ''))
        self.assertEqual(len(messages), 1, 'One warning message in the chatter of the leave')
        self.assertEqual(messages.author_id, self.odoobot.partner_id, 'The warning is posted by OdooBot')
        notifications = self.alert_notifications()
        self.assertEqual(len(notifications), 1, 'One sticky notification')
        channel, message = notifications[0]
        self.assertEqual(channel, channel_with_db(self.env.cr.dbname, user), 'Sent to the acting user')
        self.assertEqual(message['type'], 'warning')
        self.assertTrue(message['sticky'])
        self.assertIn(WARNING_TEXT, message['message'])

    def assertNotAlerted(self, leave):
        messages = leave.sudo().message_ids.filtered(lambda m: WARNING_TEXT in (m.body or ''))
        self.assertFalse(messages, 'No warning message in the chatter')
        self.assertFalse(self.alert_notifications(), 'No sticky notification')
