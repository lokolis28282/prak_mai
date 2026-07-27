from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "inventory" / "templates" / "webapp.py").read_text(encoding="utf-8")
CORE = (ROOT / "static" / "js" / "core.js").read_text(encoding="utf-8")
ROUTER = (ROOT / "static" / "js" / "router.js").read_text(encoding="utf-8")
UI = (ROOT / "static" / "js" / "ui.js").read_text(encoding="utf-8")
VACATION_FILES = (
    "core.js",
    "calendar.js",
    "requests.js",
    "employee_form.js",
    "employees.js",
    "conflicts.js",
    "index.js",
)
VACATION_SOURCES = {
    name: (ROOT / "static" / "js" / "vacations" / name).read_text(encoding="utf-8")
    for name in VACATION_FILES
}
VACATIONS = "\n".join(VACATION_SOURCES.values())


class VacationsFrontendContractTest(unittest.TestCase):
    def test_module_has_four_user_views_and_portal_entry(self) -> None:
        for view in (
            "vacations_calendar",
            "vacations_list",
            "vacations_employees",
            "vacations_conflicts",
        ):
            self.assertIn(f'id="{view}"', TEMPLATE)
            self.assertIn(view, CORE)
        self.assertIn("title:'Отпуска'", UI)
        self.assertIn("openVacations()", UI)
        self.assertIn("'vacations'", ROUTER)
        for name in VACATION_FILES:
            self.assertIn(f"vacations/{name}", TEMPLATE)

    def test_ui_exposes_calendar_roster_and_conflict_decisions(self) -> None:
        for label in (
            "Общий календарь",
            "Список отпусков",
            "Сотрудники и графики",
            "Конфликты",
            "Подтвердить исключение",
            "Отклонить отпуск",
            "Статус в Сфере",
            "Подменный",
            "Площадка",
            "График",
            "Добавить сотрудника",
        ):
            self.assertIn(label, CORE + VACATIONS)
        self.assertIn("`${V.api}/bootstrap?", VACATIONS)
        self.assertIn("/resolve", VACATIONS)
        self.assertNotIn("state.current_user.role", VACATIONS)
        self.assertNotIn("confirm(", VACATIONS)
        self.assertNotIn("prompt(", VACATIONS)
        self.assertIn("vacation-resolution-comment", VACATIONS)
        self.assertIn("].filter(Boolean)", VACATIONS)

    def test_frontend_is_split_by_user_responsibility(self) -> None:
        responsibilities = {
            "calendar.js": "V.renderCalendar",
            "requests.js": "V.renderRequests",
            "employee_form.js": "V.employeeForm",
            "employees.js": "V.renderEmployees",
            "conflicts.js": "V.renderConflicts",
        }
        for name, marker in responsibilities.items():
            self.assertIn(marker, VACATION_SOURCES[name])
            self.assertLessEqual(
                len(VACATION_SOURCES[name].splitlines()),
                180,
                f"{name} превращается в frontend-монолит",
            )
        self.assertLessEqual(len(VACATION_SOURCES["index.js"].splitlines()), 40)
        self.assertNotIn("renderElement(", VACATION_SOURCES["index.js"])


if __name__ == "__main__":
    unittest.main()
