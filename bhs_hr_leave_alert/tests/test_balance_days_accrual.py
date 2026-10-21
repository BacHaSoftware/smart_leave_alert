# -*- coding: utf-8 -*-
"""Balance per employee and type, day count like core, and accrual with open-ended allocations."""
from datetime import date

from freezegun import freeze_time

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import NOT_ENOUGH, TODAY, LeaveAlertCase


@tagged('post_install', '-at_install')
@freeze_time(TODAY)
class TestBalanceDaysAccrual(LeaveAlertCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.no_user_employee = cls.env['hr.employee'].create({
            'name': 'HLA No User',
            'resource_calendar_id': cls.calendar.id,
            'date_version': date(2025, 1, 1),
            'tz': 'UTC',
        })
        cls.compensatory_type = cls.env['hr.work.entry.type'].create({
            'name': 'HLA Compensatory',
            'code': 'HLA.COMP',
            'requires_allocation': True,
            'request_unit': 'day',
            'unit_of_measure': 'day',
            'leave_validation_type': 'hr',
            'time_off_selectable': True,
        })

    def _holiday(self, day, calendar=None):
        """Full-day closure on `day` (UTC): public holiday, or a closed day of `calendar`."""
        return self.env['resource.calendar.leaves'].create({
            'name': 'HLA holiday',
            'calendar_id': calendar.id if calendar else False,
            'date_from': f'{day} 00:00:00',
            'date_to': f'{day} 23:59:59',
        })

    # ------------------------------------------------------------------ employee without user

    def test_officer_creates_for_employee_without_user(self):
        self.allocate(10, employee=self.no_user_employee)
        leave = self.take_leave(
            date(2026, 3, 16), date(2026, 3, 16), user=self.user_officer, employee=self.no_user_employee)
        self.assertEqual(leave.employee_id, self.no_user_employee)
        self.assertEqual(leave.number_of_days, 1)

    def test_employee_without_user_still_checked(self):
        self.allocate(1, employee=self.no_user_employee)
        with self.assertRaisesRegex(UserError, NOT_ENOUGH):
            self.take_leave(
                date(2026, 3, 16), date(2026, 3, 17), user=self.user_officer, employee=self.no_user_employee)

    def test_officer_edits_leave_of_employee_without_user(self):
        self.allocate(3, employee=self.no_user_employee)
        leave = self.take_leave(
            date(2026, 3, 16), date(2026, 3, 16), user=self.user_officer, employee=self.no_user_employee)
        # an officer's request is approved at once: core only lets a leave to approve be edited
        leave.with_user(self.user_officer).action_back_to_approval()
        leave.with_user(self.user_officer).write({'request_date_to': date(2026, 3, 18)})
        self.assertEqual(leave.number_of_days, 3)

    # ------------------------------------------------------------------ balance of the leave's type only

    def test_other_type_allocation_does_not_raise_balance(self):
        self.allocate(1)
        self.allocate(10, work_entry_type=self.compensatory_type)
        with self.assertRaisesRegex(UserError, NOT_ENOUGH):
            self.take_leave(date(2026, 3, 16), date(2026, 3, 17))

    def test_other_type_allocation_does_not_hide_accrual_warning(self):
        self.allocate(12)
        self.allocate(10, work_entry_type=self.compensatory_type)
        self.take_leave(date(2026, 2, 2), date(2026, 2, 3), user=self.env.user)  # 2 days used
        self._clear_bus()
        # 2 used + 2 new = 4 > 3 months (January .. March)
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 17))
        self.assertAlerted(leave, self.user_employee)

    def test_other_type_allocation_on_write(self):
        self.allocate(2)
        self.allocate(10, work_entry_type=self.compensatory_type)
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 16))
        with self.assertRaisesRegex(UserError, NOT_ENOUGH):
            leave.with_user(self.user_employee).write({'request_date_to': date(2026, 3, 18)})

    # ------------------------------------------------------------------ days counted like core

    def test_public_holiday_is_not_a_leave_day(self):
        self.allocate(2)
        self._holiday('2026-03-18')
        # Tue 17 - Thu 19 with Wed 18 a public holiday: 2 leave days
        leave = self.take_leave(date(2026, 3, 17), date(2026, 3, 19))
        self.assertEqual(leave.number_of_days, 2)

    def test_calendar_closed_day_is_not_a_leave_day(self):
        self.allocate(2)
        self._holiday('2026-03-18', calendar=self.calendar)
        leave = self.take_leave(date(2026, 3, 17), date(2026, 3, 19))
        self.assertEqual(leave.number_of_days, 2)

    def test_public_holiday_on_write(self):
        self.allocate(2)
        self._holiday('2026-03-18')
        leave = self.take_leave(date(2026, 3, 17), date(2026, 3, 17))
        leave.with_user(self.user_employee).write({'request_date_to': date(2026, 3, 19)})
        self.assertEqual(leave.number_of_days, 2)

    def test_public_holiday_not_counted_for_accrual(self):
        self.allocate(12)
        self._holiday('2026-03-18')
        self.take_leave(date(2026, 2, 2), date(2026, 2, 2), user=self.env.user)  # 1 day used
        self._clear_bus()
        # Tue 17 - Thu 19 = 2 leave days: 1 + 2 = 3 months, no warning (counted Mon-Fri: 1 + 3 > 3)
        leave = self.take_leave(date(2026, 3, 17), date(2026, 3, 19))
        self.assertNotAlerted(leave)

    # ------------------------------------------------------------------ allocation without end date

    def test_open_allocation_of_this_year_counts_for_accrual(self):
        self.allocate(12, date_to=False)
        self.take_leave(date(2026, 2, 2), date(2026, 2, 3), user=self.env.user)  # 2 days used
        self._clear_bus()
        # 2 used + 2 new = 4 > 3 months (January .. March)
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 17))
        self.assertAlerted(leave, self.user_employee)

    def test_open_allocation_of_this_year_within_accrual(self):
        self.allocate(12, date_to=False)
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 17))  # 2 <= 3 months
        self.assertNotAlerted(leave)

    def test_open_allocation_months_from_its_start(self):
        self.allocate(12, date_from=date(2026, 3, 1), date_to=False)
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 17))  # 2 > 1 month (March)
        self.assertAlerted(leave, self.user_employee)

    def test_open_allocation_of_earlier_year_is_ignored(self):
        self.allocate(12, date_from=date(2025, 1, 1), date_to=False)
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 20))  # 5 days, no allocation of this year
        self.assertNotAlerted(leave)
