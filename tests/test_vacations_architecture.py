from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
VACATIONS = ROOT / "inventory" / "vacations"


class VacationsArchitectureTest(unittest.TestCase):
    def test_backend_is_split_by_domain_responsibility(self) -> None:
        responsibilities = {
            "validation.py": "class VacationValidationRules",
            "conflict_rules.py": "class VacationConflictRules",
            "calendar.py": "class VacationCalendarRules",
            "repositories/employees.py": "class VacationEmployeeRepository",
            "repositories/registrations.py": "class VacationRegistrationRepository",
            "repositories/requests.py": "class VacationRequestRepository",
            "repositories/conflicts.py": "class VacationConflictRepository",
            "repositories/audit.py": "class VacationAuditRepository",
        }
        for relative, marker in responsibilities.items():
            source = (VACATIONS / relative).read_text(encoding="utf-8")
            self.assertIn(marker, source)
            self.assertLessEqual(
                len(source.splitlines()),
                260,
                f"{relative} превращается в backend-монолит",
            )

    def test_public_service_and_repository_are_composition_shells(self) -> None:
        service = (VACATIONS / "service.py").read_text(encoding="utf-8")
        repository = (VACATIONS / "repository.py").read_text(encoding="utf-8")
        self.assertLessEqual(len(service.splitlines()), 60)
        self.assertLessEqual(len(repository.splitlines()), 60)
        self.assertNotIn("SELECT ", service)
        self.assertNotIn("INSERT ", service)
        self.assertNotIn("UPDATE ", service)
        self.assertNotIn("vacation_requests", repository)


if __name__ == "__main__":
    unittest.main()
