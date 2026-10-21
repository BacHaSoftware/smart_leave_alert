# -*- coding: utf-8 -*-
"""A paid leave outside its 2026 allocation is refused on every channel: form, ORM/RPC create and write."""
import re
from datetime import date

from freezegun import freeze_time

from odoo.exceptions import ValidationError
from odoo.tests import Form, new_test_user, tagged

from .common import TODAY, LeaveAlertCase

PERIOD_MESSAGE = re.escape('You do not have a valid leave allocation covering the selected dates.')
OUTSIDE_DAY = date(2027, 1, 4)  # Monday, after the end of the 2026 allocation


@tagged('post_install', '-at_install')
@freeze_time(TODAY)
class TestAllocationPeriod(LeaveAlertCase):

    def setUp(self):
        super().setUp()
        self.allocate(12)

    def _leave_count(self, employee=None):
        return self.env['hr.leave'].sudo().search_count([('employee_id', '=', (employee or self.employee).id)])

    def _form_outside_period(self, model):
        form = Form(model)
        form.work_entry_type_id = self.paid_type
        form.request_date_from = OUTSIDE_DAY
        form.request_date_to = OUTSIDE_DAY
        return form

    # ------------------------------------------------------------------ Time Off form

    def test_form_employee_outside_period_refused(self):
        before = self._leave_count()
        model = self.env['hr.leave'].with_user(self.user_employee).with_context(default_employee_id=self.employee.id)
        form = self._form_outside_period(model)
        self.assertEqual(form.work_entry_type_id, self.paid_type, 'The paid type is kept by the onchange')
        self.assertEqual(form.request_date_from, OUTSIDE_DAY)
        self.assertEqual(form.request_date_to, OUTSIDE_DAY)
        with self.assertRaisesRegex(ValidationError, PERIOD_MESSAGE):
            form.save()
        self.assertEqual(self._leave_count(), before, 'No leave is created')

    def test_form_officer_outside_period_refused(self):
        before = self._leave_count()
        model = self.env['hr.leave'].with_user(self.user_officer).with_context(default_employee_id=self.employee.id)
        form = self._form_outside_period(model)
        self.assertEqual(form.work_entry_type_id, self.paid_type, 'No swap to a type without allocation')
        with self.assertRaisesRegex(ValidationError, PERIOD_MESSAGE):
            form.save()
        self.assertEqual(self._leave_count(), before, 'No leave is created')

    def test_form_inside_period_created(self):
        model = self.env['hr.leave'].with_user(self.user_employee).with_context(default_employee_id=self.employee.id)
        with Form(model) as form:
            form.work_entry_type_id = self.paid_type
            form.request_date_from = date(2026, 11, 2)
            form.request_date_to = date(2026, 11, 2)
        self.assertEqual(form.record.work_entry_type_id, self.paid_type)
        self.assertEqual(form.record.number_of_days, 1)

    # ------------------------------------------------------------------ ORM / RPC / import

    def test_create_outside_period_refused(self):
        before = self._leave_count()
        with self.assertRaisesRegex(ValidationError, PERIOD_MESSAGE):
            self.take_leave(OUTSIDE_DAY, OUTSIDE_DAY)
        self.assertEqual(self._leave_count(), before)

    def test_create_outside_period_refused_for_officer(self):
        before = self._leave_count()
        with self.assertRaisesRegex(ValidationError, PERIOD_MESSAGE):
            self.take_leave(OUTSIDE_DAY, OUTSIDE_DAY, user=self.user_officer)
        self.assertEqual(self._leave_count(), before)

    def test_create_across_period_end_refused(self):
        """Thu 31 Dec 2026 .. Mon 4 Jan 2027: the end is outside the allocation."""
        before = self._leave_count()
        with self.assertRaisesRegex(ValidationError, PERIOD_MESSAGE):
            self.take_leave(date(2026, 12, 31), OUTSIDE_DAY)
        self.assertEqual(self._leave_count(), before)

    def test_write_dates_out_of_period_refused(self):
        leave = self.take_leave(date(2026, 11, 2), date(2026, 11, 2))
        with self.assertRaisesRegex(ValidationError, PERIOD_MESSAGE):
            leave.with_user(self.user_employee).write({
                'request_date_from': OUTSIDE_DAY,
                'request_date_to': OUTSIDE_DAY,
            })
        self.assertEqual(leave.request_date_from, date(2026, 11, 2), 'The leave is unchanged')
        self.assertEqual(leave.request_date_to, date(2026, 11, 2))

    def test_create_inside_period(self):
        leave = self.take_leave(date(2026, 11, 2), date(2026, 11, 3))
        self.assertTrue(leave)
        self.assertEqual(leave.number_of_days, 2)

    def test_type_without_allocation_not_checked(self):
        leave = self.take_leave(OUTSIDE_DAY, OUTSIDE_DAY, work_entry_type=self.other_type)
        self.assertTrue(leave)

    def test_multi_leave_request_left_to_core(self):
        """Core multi-employee batch: the module check is skipped, core drops the invalid leave itself."""
        leaves = self.env['hr.leave'].with_context(multi_leave_request=True).create(
            self.leave_vals(OUTSIDE_DAY, OUTSIDE_DAY))
        self.assertFalse(leaves, 'Core removed the leave without a valid allocation')

    def test_multi_leave_request_by_time_off_responsible_left_to_core(self):
        """A Time Off Responsible batch is left to core; an employee sending the same key is refused."""
        responsible = new_test_user(self.env, login='hla_responsible', tz='UTC', email='hla_responsible@example.com',
                                    groups='base.group_user,hr_holidays.group_hr_holidays_responsible')
        # core 20 keeps the Responsible group only on users who approve someone's time off
        self.employee.leave_manager_id = responsible
        self.assertTrue(responsible.has_group('hr_holidays.group_hr_holidays_responsible'))
        leave = self.env['hr.leave'].with_context(skip_allocation_check=True).create(
            self.leave_vals(OUTSIDE_DAY, OUTSIDE_DAY))
        self.assertIn(leave.state, ('confirm', 'validate1', 'validate'))  # states the check covers
        batch = leave.with_context(multi_leave_request=True)
        batch.with_user(responsible)._check_leave_within_allocation_period()  # no refusal
        with self.assertRaisesRegex(ValidationError, PERIOD_MESSAGE):
            batch.with_user(self.user_employee)._check_leave_within_allocation_period()

    def test_employee_cannot_bypass_with_context(self):
        """The core bypass keys are honoured only for trusted callers: an employee sending them by RPC is refused."""
        before = self._leave_count()
        for key in ('skip_allocation_check', 'multi_leave_request'):
            with self.subTest(key=key), self.assertRaisesRegex(ValidationError, PERIOD_MESSAGE):
                self.env['hr.leave'].with_user(self.user_employee).with_context(**{key: True}).create(
                    self.leave_vals(OUTSIDE_DAY, OUTSIDE_DAY))
        self.assertEqual(self._leave_count(), before)
