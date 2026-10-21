# -*- coding: utf-8 -*-
"""Annual leave alert. Today = 2026-03-10 (Tuesday); leave days Monday-Friday, 0.5 for a half day."""
from datetime import date

from freezegun import freeze_time

from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from odoo.addons.bus.models.bus import channel_with_db

from .common import NOT_ENOUGH, TODAY, WARNING_TEXT, LeaveAlertCase


@tagged('post_install', '-at_install')
@freeze_time(TODAY)
class TestLeaveAlert(LeaveAlertCase):

    # ------------------------------------------------------------------ create

    def test_enough_balance_creates_leave_without_warning(self):
        self.allocate(10)
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 18))  # Mon-Wed: 3 days
        self.assertTrue(leave)
        self.assertEqual(leave.number_of_days, 3)
        self.assertNotAlerted(leave)

    def test_not_enough_balance_blocks_creation(self):
        self.allocate(2)
        Leave = self.env['hr.leave'].sudo()
        before = Leave.search_count([('employee_id', '=', self.employee.id)])
        with self.assertRaisesRegex(UserError, NOT_ENOUGH):
            self.take_leave(date(2026, 3, 16), date(2026, 3, 18))
        self.assertEqual(Leave.search_count([('employee_id', '=', self.employee.id)]), before)

    def test_weekend_days_are_not_counted(self):
        self.allocate(2)
        # Fri 2026-03-13 .. Mon 2026-03-16: two weekdays, the weekend is free
        leave = self.take_leave(date(2026, 3, 13), date(2026, 3, 16))
        self.assertTrue(leave)

    def test_half_day_counts_half(self):
        self.allocate(0.5)
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 16), request_duration='am')
        self.assertTrue(leave)
        self.assertEqual(leave.number_of_days, 0.5)
        self.assertNotAlerted(leave)

    def test_half_day_afternoon_counts_half(self):
        self.allocate(0.5)
        leave = self.take_leave(date(2026, 3, 17), date(2026, 3, 17), request_duration='pm')
        self.assertTrue(leave)

    def test_full_day_needs_full_balance(self):
        self.allocate(0.5)
        with self.assertRaisesRegex(UserError, NOT_ENOUGH):
            self.take_leave(date(2026, 3, 16), date(2026, 3, 16), request_duration='full')

    def test_over_monthly_accrual_warns(self):
        self.allocate(12)
        used = self.take_leave(date(2026, 2, 2), date(2026, 2, 4), user=self.env.user)  # 3 days, auto-approved
        self.assertNotAlerted(used)
        self._clear_bus()
        # used 3 + new 2 = 5 > 3 months (January .. March)
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 17))
        self.assertTrue(leave, 'The warning does not block the request')
        self.assertAlerted(leave, self.user_employee)

    def test_within_monthly_accrual_no_warning(self):
        self.allocate(12)
        self.take_leave(date(2026, 2, 2), date(2026, 2, 3), user=self.env.user)  # 2 days
        self._clear_bus()
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 16))  # 2 + 1 = 3 months: no warning
        self.assertNotAlerted(leave)

    def test_other_type_is_not_checked(self):
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 18), work_entry_type=self.other_type)
        self.assertTrue(leave)
        self.assertNotAlerted(leave)

    def test_generic_paid_type_is_checked(self):
        """Any work entry type with code 016.00 is paid time off (one legal leave type per country), e.g. the generic one."""
        generic = self.env.ref('hr_work_entry.generic_work_entry_type_legal_leave')
        self.assertEqual(generic.code, '016.00')
        with self.assertRaisesRegex(UserError, NOT_ENOUGH):
            self.take_leave(date(2026, 3, 16), date(2026, 3, 18), work_entry_type=generic)

    # ------------------------------------------------------------------ values not sent by the form

    def _own_create(self, vals):
        """Like the Odoo 20 web client: employee_id is not in vals, the action gives default_employee_id."""
        vals = dict(vals)
        del vals['employee_id']
        return self.env['hr.leave'].with_user(self.user_employee).with_context(
            default_employee_id=self.employee.id).create(vals)

    def test_own_request_without_employee_in_vals(self):
        self.allocate(10)
        leave = self._own_create(self.leave_vals(date(2026, 3, 16), date(2026, 3, 18)))
        self.assertEqual(leave.employee_id, self.employee)

    def test_own_request_without_employee_in_vals_not_enough(self):
        self.allocate(2)
        with self.assertRaisesRegex(UserError, NOT_ENOUGH):
            self._own_create(self.leave_vals(date(2026, 3, 16), date(2026, 3, 18)))

    def test_type_from_context_default_is_checked(self):
        self.allocate(2)
        vals = self.leave_vals(date(2026, 3, 16), date(2026, 3, 18))
        del vals['work_entry_type_id']
        Leave = self.env['hr.leave'].with_user(self.user_employee).with_context(
            default_work_entry_type_id=self.paid_type.id)
        with self.assertRaisesRegex(UserError, NOT_ENOUGH):
            Leave.create(vals)

    def test_employee_from_context_default_is_checked(self):
        """Officer opens the form from the employee (default_employee_id), employee_id not in vals."""
        self.allocate(2)
        vals = self.leave_vals(date(2026, 3, 16), date(2026, 3, 18))
        del vals['employee_id']
        Leave = self.env['hr.leave'].with_user(self.user_officer).with_context(default_employee_id=self.employee.id)
        with self.assertRaisesRegex(UserError, NOT_ENOUGH):
            Leave.create(vals)

    def _own_model(self):
        return self.env['hr.leave'].with_user(self.user_employee).with_context(default_employee_id=self.employee.id)

    def test_form_own_request(self):
        self.allocate(10)
        with Form(self._own_model()) as form:
            form.work_entry_type_id = self.paid_type
            form.request_date_from = date(2026, 3, 16)
            form.request_date_to = date(2026, 3, 18)
        leave = form.record
        self.assertEqual(leave.employee_id, self.employee)
        self.assertEqual(leave.number_of_days, 3)

    def test_form_own_request_not_enough(self):
        self.allocate(2)
        form = Form(self._own_model())
        form.work_entry_type_id = self.paid_type
        form.request_date_from = date(2026, 3, 16)
        form.request_date_to = date(2026, 3, 18)
        with self.assertRaisesRegex(UserError, NOT_ENOUGH):
            form.save()

    def test_form_own_half_day(self):
        self.allocate(0.5)
        with Form(self._own_model()) as form:
            form.work_entry_type_id = self.paid_type
            form.request_date_from = date(2026, 3, 16)
            form.request_date_to = date(2026, 3, 16)
            form.request_duration = 'am'
        self.assertEqual(form.record.number_of_days, 0.5)

    def test_form_over_monthly_accrual_warns(self):
        self.allocate(12)
        self.take_leave(date(2026, 2, 2), date(2026, 2, 4), user=self.env.user)
        self._clear_bus()
        with Form(self._own_model()) as form:
            form.work_entry_type_id = self.paid_type
            form.request_date_from = date(2026, 3, 16)
            form.request_date_to = date(2026, 3, 17)
        self.assertAlerted(form.record, self.user_employee)

    # ------------------------------------------------------------------ write

    def test_edit_end_date_rechecks_with_old_days_given_back(self):
        self.allocate(3)
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 17))  # 2 days, remaining 1
        leave.with_user(self.user_employee).write({'request_date_to': date(2026, 3, 18)})  # 3 <= 1 + 2
        self.assertEqual(leave.request_date_to, date(2026, 3, 18))
        with self.assertRaisesRegex(UserError, NOT_ENOUGH):
            leave.with_user(self.user_employee).write({'request_date_to': date(2026, 3, 20)})  # 5 > 3
        self.assertEqual(leave.request_date_to, date(2026, 3, 18))

    def test_edit_end_date_as_string(self):
        self.allocate(3)
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 17))
        with self.assertRaisesRegex(UserError, NOT_ENOUGH):
            leave.with_user(self.user_employee).write({'request_date_to': '2026-03-20'})

    def test_edit_start_date_as_string(self):
        """A string request_date_from is accepted."""
        self.allocate(3)
        leave = self.take_leave(date(2026, 3, 17), date(2026, 3, 18))  # 2 days, remaining 1
        leave.with_user(self.user_employee).write({'request_date_from': '2026-03-16'})  # 3 <= 1 + 2
        self.assertEqual(leave.request_date_from, date(2026, 3, 16))

    def test_edit_start_date_as_string_not_enough(self):
        self.allocate(2)
        leave = self.take_leave(date(2026, 3, 17), date(2026, 3, 18))  # 2 days, remaining 0
        with self.assertRaisesRegex(UserError, NOT_ENOUGH):
            leave.with_user(self.user_employee).write({'request_date_from': '2026-03-16'})  # 3 > 0 + 2
        self.assertEqual(leave.request_date_from, date(2026, 3, 17))

    def test_edit_half_day_leave_counts_half(self):
        self.allocate(0.5)
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 16), request_duration='am')
        leave.with_user(self.user_employee).write({
            'request_date_from': date(2026, 3, 17), 'request_date_to': date(2026, 3, 17)})
        self.assertEqual(leave.request_date_from, date(2026, 3, 17))

    def test_edit_full_day_to_half_day_uses_new_duration(self):
        """request_duration in the written values wins over the stored one: only 0.5 left -> a morning fits."""
        self.allocate(0.5)
        leave = self.take_leave(date(2026, 3, 14), date(2026, 3, 14))  # full day on a Saturday: 0 weekdays
        self.assertEqual(leave.request_duration, 'full')
        leave.with_user(self.user_employee).write({
            'request_duration': 'am', 'request_date_from_period': 'am', 'request_date_to_period': 'am',
            'request_date_from': date(2026, 3, 16), 'request_date_to': date(2026, 3, 16)})
        self.assertEqual(leave.request_date_from, date(2026, 3, 16))
        self.assertEqual(leave.request_duration, 'am')

    def test_edit_half_day_to_full_day_not_enough(self):
        self.allocate(0.5)
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 16), request_duration='am')  # remaining 0
        with self.assertRaisesRegex(UserError, NOT_ENOUGH):
            leave.with_user(self.user_employee).write({
                'request_duration': 'full', 'request_date_from_period': 'am', 'request_date_to_period': 'pm',
                'request_date_to': date(2026, 3, 16)})  # 1 day > 0 + 0.5 given back
        self.assertEqual(leave.request_duration, 'am')

    def test_edit_over_monthly_accrual_warns(self):
        self.allocate(12)
        self.take_leave(date(2026, 2, 2), date(2026, 2, 4), user=self.env.user)  # 3 days
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 16))  # 3 + 1 = 4 > 3: warned at creation
        self._clear_bus()
        leave.with_user(self.user_employee).write({'request_date_to': date(2026, 3, 17)})
        notifications = self.alert_notifications()
        self.assertEqual(len(notifications), 1)

    def test_edit_other_fields_not_checked(self):
        self.allocate(2)
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 17))
        leave.with_user(self.user_employee).write({'notes': 'HLA note'})
        self.assertEqual(leave.notes, 'HLA note')

    def test_edit_other_type_not_checked(self):
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 17), work_entry_type=self.other_type)
        leave.with_user(self.user_employee).write({'request_date_to': date(2026, 3, 20)})
        self.assertEqual(leave.request_date_to, date(2026, 3, 20))

    # ------------------------------------------------------------------ several allocations

    def test_two_allocations_are_summed(self):
        """Two validated paid allocations in the year are summed (no 'Expected singleton')."""
        self.allocate(6)
        self.allocate(6)
        self.assertEqual(self.remaining(), 12)
        self.take_leave(date(2026, 2, 2), date(2026, 2, 4), user=self.env.user)  # 3 days
        self._clear_bus()
        # (6 + 6 - 9) + 2 = 5 > 3 months -> warning
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 17))
        self.assertAlerted(leave, self.user_employee)

    def test_two_allocations_earliest_month(self):
        """Months worked are counted from the earliest allocation start (February -> 2 months)."""
        self.allocate(6, date_from=date(2026, 2, 1))
        self.allocate(6, date_from=date(2026, 3, 1))
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 17))  # 2 days <= 2 months
        self.assertNotAlerted(leave)
        self._clear_bus()
        leave = self.take_leave(date(2026, 3, 18), date(2026, 3, 18))  # 3 days > 2 months
        self.assertAlerted(leave, self.user_employee)

    def test_two_allocations_on_write(self):
        self.allocate(6)
        self.allocate(6)
        leave = self.take_leave(date(2026, 3, 16), date(2026, 3, 16))
        self._clear_bus()
        leave.with_user(self.user_employee).write({'request_date_to': date(2026, 3, 19)})  # 4 > 3
        self.assertEqual(len(self.alert_notifications()), 1)

    # ------------------------------------------------------------------ roles

    def _form_for_employee(self, user):
        form = Form(self.env['hr.leave'].with_user(user).with_context(default_employee_id=self.employee.id))
        form.work_entry_type_id = self.paid_type
        form.request_date_from = date(2026, 3, 16)
        form.request_date_to = date(2026, 3, 18)
        return form

    def test_roles_same_outcome_not_enough(self):
        self.allocate(2)
        for user in (self.user_employee, self.user_officer, self.user_manager):
            with self.subTest(role=user.login):
                form = self._form_for_employee(user)
                with self.assertRaisesRegex(UserError, NOT_ENOUGH):
                    form.save()

    def test_roles_same_outcome_enough(self):
        self.allocate(12)
        for user in (self.user_employee, self.user_officer, self.user_manager):
            with self.subTest(role=user.login):
                leave = self._form_for_employee(user).save()
                self.assertEqual(leave.employee_id, self.employee)
                self.assertEqual(leave.number_of_days, 3)
                # refuse so that the next role starts with the same balance
                leave.with_env(self.env).action_refuse()

    def test_roles_warning_goes_to_acting_user(self):
        for user in (self.user_officer, self.user_manager):
            with self.subTest(role=user.login):
                allocation = self.allocate(12)
                used = self.take_leave(date(2026, 2, 2), date(2026, 2, 4), user=self.env.user)
                self._clear_bus()
                form = Form(self.env['hr.leave'].with_user(user).with_context(default_employee_id=self.employee.id))
                form.work_entry_type_id = self.paid_type
                form.request_date_from = date(2026, 3, 16)
                form.request_date_to = date(2026, 3, 17)
                leave = form.save()
                self.assertAlerted(leave, user)
                (leave | used).with_env(self.env).action_refuse()
                allocation.with_env(self.env).action_refuse()
                self._clear_bus()

    def test_employee_sees_only_own_allocations(self):
        own = self.allocate(5)
        other = self.allocate(5, employee=self.other_employee)
        visible = self.env['hr.leave.allocation'].with_user(self.user_employee).search([])
        self.assertIn(own, visible)
        self.assertNotIn(other, visible)
        officer_visible = self.env['hr.leave.allocation'].with_user(self.user_officer).search([])
        self.assertIn(other, officer_visible)

    def test_officer_creates_for_other_employee(self):
        self.allocate(2, employee=self.other_employee)
        with self.assertRaisesRegex(UserError, NOT_ENOUGH):
            self.take_leave(date(2026, 3, 16), date(2026, 3, 18), user=self.user_officer, employee=self.other_employee)
        leave = self.take_leave(
            date(2026, 3, 16), date(2026, 3, 17), user=self.user_officer, employee=self.other_employee)
        self.assertEqual(leave.employee_id, self.other_employee)

    def test_multi_create_over_accrual_one_notification(self):
        """A batch that exceeds the accrual: one sticky notification, an OdooBot message on each leave."""
        self.allocate(12)
        self.take_leave(date(2026, 2, 2), date(2026, 2, 4), user=self.env.user)  # 3 days used
        self._clear_bus()
        leaves = self.env['hr.leave'].with_user(self.user_officer).create([
            self.leave_vals(date(2026, 3, 16), date(2026, 3, 17)),  # 3 + 2 = 5 > 3 months
            self.leave_vals(date(2026, 3, 18), date(2026, 3, 18)),
        ])
        self.assertEqual(len(leaves), 2)
        notifications = self.alert_notifications()
        self.assertEqual(len(notifications), 1, 'One notification for the whole batch')
        self.assertEqual(notifications[0][0], channel_with_db(self.env.cr.dbname, self.user_officer))
        for leave in leaves:
            messages = leave.sudo().message_ids.filtered(lambda m: WARNING_TEXT in (m.body or ''))
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages.author_id, self.odoobot.partner_id)

    def test_multi_create_warns_only_leaves_over_accrual(self):
        """In a batch, only the leave that exceeds the accrual gets the OdooBot warning."""
        self.allocate(12)
        self.take_leave(date(2026, 2, 2), date(2026, 2, 2), user=self.env.user)  # 1 day used
        self._clear_bus()
        within, over = self.env['hr.leave'].with_user(self.user_officer).create([
            self.leave_vals(date(2026, 3, 16), date(2026, 3, 16)),  # 1 + 1 = 2 <= 3 months
            self.leave_vals(date(2026, 3, 23), date(2026, 3, 25)),  # 1 + 3 = 4 > 3 months
        ])
        flags = [
            bool(leave.sudo().message_ids.filtered(lambda m: WARNING_TEXT in (m.body or '')))
            for leave in (within, over)
        ]
        self.assertEqual(flags, [False, True], 'Warning only on the leave above the accrual')
        self.assertEqual(len(self.alert_notifications()), 1, 'One notification for the whole batch')

    def test_multi_create(self):
        self.allocate(5)
        self.allocate(5, employee=self.other_employee)
        leaves = self.env['hr.leave'].with_user(self.user_officer).create([
            self.leave_vals(date(2026, 3, 16), date(2026, 3, 17)),
            self.leave_vals(date(2026, 3, 16), date(2026, 3, 17), employee=self.other_employee),
        ])
        self.assertEqual(leaves.employee_id, self.employee | self.other_employee)
