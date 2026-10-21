# -*- coding: utf-8 -*-
"""Clickbot over the Time Off app for each role (slow, run explicitly); any JS/RPC/access error fails."""
from datetime import date, timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged

from .common import TZ_UI

APPS: list[str] = ['hr_holidays.menu_hr_holidays_root']
# No base.default_user_group: on the shared test database it may imply HR rights, the low roles must stay low.
ROLES = {
    'click_hla_admin': ['base.group_user', 'base.group_system', 'hr_holidays.group_hr_holidays_manager'],
    'click_hla_officer': ['base.group_user', 'hr_holidays.group_hr_holidays_user'],
    'click_hla_employee': ['base.group_user', 'hr_holidays.group_hr_holidays_employee'],
}


@tagged('click_all', 'post_install', '-at_install', '-standard')
class TestFunctionalUI(HttpCase):

    def _make_user(self, login, groups):
        group_ids = [self.env.ref(g).id for g in groups]
        existing = self.env['res.users'].search([('login', '=', login)])
        if existing:
            existing.write({'group_ids': [(6, 0, group_ids)], 'password': login, 'tz': TZ_UI})
            return existing
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'password': login, 'email': f'{login}@click.example.com', 'tz': TZ_UI,
            'group_ids': [(6, 0, group_ids)],
        })

    def _paid_type(self):
        country = self.env.company.country_id
        return self.env['hr.work.entry.type'].search([
            ('code', '=', '016.00'), ('country_id', 'in', country.ids + [False]), ('requires_allocation', '=', True),
        ], order='country_id', limit=1)

    def _seed_data(self, users):
        """Per role: an employee, a validated paid allocation for the year and one paid leave request."""
        paid_type = self._paid_type()
        self.assertTrue(paid_type, 'A paid time off type (code 016.00) is visible to the company')
        today = fields.Date.today()
        next_monday = today + timedelta(days=7 - today.weekday())
        # the allocation must be active today and cover the leave, even when next Monday is in the next year
        allocation_end = date((next_monday + timedelta(days=1)).year, 12, 31)
        for user in users:
            employee = user.employee_id or self.env['hr.employee'].create({'name': f'HLA {user.login}', 'user_id': user.id})
            allocation = self.env['hr.leave.allocation'].create({
                'name': 'HLA click allocation', 'employee_id': employee.id, 'work_entry_type_id': paid_type.id,
                'number_of_days': 12, 'date_from': date(today.year, 1, 1), 'date_to': allocation_end,
            })
            allocation.action_approve()
            self.env['hr.leave'].with_user(user).create({
                'employee_id': employee.id, 'work_entry_type_id': paid_type.id,
                'request_date_from': next_monday, 'request_date_to': next_monday + timedelta(days=1),
            })

    def _hide_core_in_contract_filter(self):
        """Odoo 20 core bug: the 'In Contract' filter reads employee_id.contract_date_start (hr.group_hr_user);
        hide it from employees in this test."""
        self.env['ir.ui.view'].create({
            'name': 'hla.test.hide.in_contract',
            'type': 'search',
            'model': 'hr.leave',
            'inherit_id': self.env.ref('hr_holidays.view_hr_holidays_filter').id,
            'arch': '<filter name="in_contract" position="attributes">'
                    '<attribute name="groups">hr.group_hr_user</attribute></filter>',
        })

    def test_clickbot_module_apps(self):
        users = [self._make_user(login, groups) for login, groups in ROLES.items()]
        self._seed_data(users)
        self._hide_core_in_contract_filter()
        for user in users:
            visible = self.env['ir.ui.menu'].with_user(user)._visible_menu_ids()
            for xmlid in APPS:
                self.assertIn(self.env.ref(xmlid).id, visible, f"Role {user.login} must see app {xmlid}")
                with self.subTest(role=user.login, app=xmlid):
                    self.browser_js(
                        '/odoo',
                        "odoo.loader.modules.get('@web/webclient/clickbot/clickbot_loader')"
                        f".startClickEverywhere({{ xmlId: '{xmlid}', logger: true }});",
                        login=user.login, timeout=1200, success_signal='clickbot test succeeded')
