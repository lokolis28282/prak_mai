import unittest

from inventory.warehouse.classification import (
    UNKNOWN_ITEM_NAME,
    canonical_vendor,
    classify_card,
    clean_item_name,
    operational_category,
)
from inventory.warehouse.validators import soft_receipt_source


class WarehouseClassificationTest(unittest.TestCase):
    def assert_type(self, expected_field: str, expected_value: str, **values: str) -> None:
        result = classify_card(**values)
        self.assertEqual((result.field, result.value), (expected_field, expected_value))

    def test_representative_datacenter_families(self) -> None:
        cases = (
            ("equipment_type", "Сервер", {"item_name": "Dell PowerEdge R760"}),
            ("equipment_type", "Коммутатор", {"item_name": "Huawei CloudEngine CE6863E-48S6CQ"}),
            ("equipment_type", "Маршрутизатор", {"item_name": "Juniper MX-304"}),
            ("equipment_type", "Система хранения данных", {"item_name": "HP Primera C650 2U"}),
            ("component_type", "Сетевой адаптер", {"item_name": "ConnectX-4 Lx", "model": "MCX4121A-ACAT"}),
            ("component_type", "Сетевой адаптер", {"item_name": "Intel X710 adapter"}),
            ("component_type", "SSD", {"item_name": "Samsung PM1733"}),
            ("component_type", "SSD", {"item_name": "Micron 7450 NVMe"}),
            ("component_type", "Оперативная память", {"item_name": "DDR4 64GB RDIMM"}),
            ("component_type", "Оперативная память", {"item_name": "Компонент MICRON 64Gb 3200Mhz"}),
            ("component_type", "Плата", {"item_name": "Компонент HUAWEI Raiser"}),
            ("component_type", "Плата", {"item_name": "Компонент CISCO NIM-24A V03"}),
            ("component_type", "Трансивер", {"item_name": "QSFP28-100G-SR4"}),
            ("cable_type", "DAC", {"item_name": "DAC-кабель"}),
            ("cable_type", "DAC", {"item_name": "Huawei QSFP-DD-400G-CU1M"}),
            ("cable_type", "AOC", {"item_name": "MT-QSFP-100G-AOC-15-CD"}),
            ("equipment_type", "Система хранения данных", {"item_name": "Полка JBOD 12x20TB HDD"}),
            ("equipment_type", "Система хранения данных", {"item_name": "Dell PowerStore 5200"}),
            ("equipment_type", "Межсетевой экран", {"item_name": "Palo Alto PAN-PA-5400"}),
            ("equipment_type", "Балансировщик нагрузки", {"item_name": "Коммутатор Radware ALTEON D5424S"}),
            ("equipment_type", "Маршрутизатор", {"item_name": "Коммутатор Cisco ISR4221"}),
            ("equipment_type", "Сервер", {"item_name": "Сервер GPU 8_H200 Dell XE9680"}),
            ("component_type", "Плата", {"item_name": "Бэкплейн Lenovo SR590"}),
            ("component_type", "HBA-адаптер", {"item_name": "RAID-контроллер Dell LPe35002"}),
            ("component_type", "Сетевой адаптер", {"item_name": "Карта HPE 562 FLR-SFP+"}),
            ("component_type", "Трансивер", {"item_name": "Сетевой адаптер Huawei OMXD30000"}),
            ("component_type", "Сетевой адаптер", {"item_name": "Коммутатор PALO ALTO PAN-PA-5400-NC-A"}),
            ("equipment_type", "Коммутатор", {"item_name": "Сетевой адаптер Huawei XH9230-128DQ"}),
        )
        for field, value, inputs in cases:
            with self.subTest(inputs=inputs):
                self.assert_type(field, value, **inputs)

    def test_vendor_normalization_does_not_merge_known_distinct_brands(self) -> None:
        self.assertEqual(canonical_vendor("DELL INC"), "Dell")
        self.assertEqual(canonical_vendor("INTEL CORPORATION"), "Intel")
        self.assertEqual(canonical_vendor("KIOXIA CORPORATION"), "Kioxia")
        self.assertEqual(canonical_vendor("HP"), "HP")
        self.assertEqual(canonical_vendor("HPE"), "HPE")
        self.assertEqual(canonical_vendor("Hunix"), "Hunix")
        self.assertEqual(canonical_vendor("Hynix"), "Hynix")

    def test_na_is_replaced_with_explicit_non_fabricated_placeholder(self) -> None:
        self.assertEqual(clean_item_name("#N/A"), UNKNOWN_ITEM_NAME)
        result = classify_card(item_name=UNKNOWN_ITEM_NAME)
        self.assertEqual(result.confidence, "LOW")

    def test_generic_component_label_does_not_override_specific_existing_type(self) -> None:
        self.assert_type(
            "component_type",
            "SSD",
            item_name="Компонент MICRON 7500 PRO",
            vendor="Micron",
            model="7500 PRO",
            component_type="SSD",
        )

    def test_operator_facing_categories_are_specific_and_stable(self) -> None:
        cases = (
            ("Оборудование", {"equipment_type": "Сервер"}),
            ("Трансиверы", {"component_type": "Трансивер"}),
            ("Память", {"component_type": "Оперативная память"}),
            ("Накопители", {"component_type": "SSD"}),
            ("Адаптеры и контроллеры", {"component_type": "HBA-адаптер"}),
            ("Комплектующие", {"component_type": "GPU"}),
            ("Другое оборудование", {"component_type": "Аксессуар"}),
            ("Кабели", {"cable_type": "OM4"}),
            ("Кабельные сборки", {"cable_type": "DAC"}),
            ("Другое оборудование", {"component_type": "Прочий компонент"}),
        )
        for expected, values in cases:
            with self.subTest(values=values):
                self.assertEqual(operational_category(**values), expected)

    def test_san_card_is_an_hba_adapter(self) -> None:
        self.assert_type("component_type", "HBA-адаптер", item_name="Карта SAN Emulex")

    def test_soft_import_automatically_classifies_new_cards(self) -> None:
        row = soft_receipt_source({
            "item_name": "Dell PowerEdge R760", "serial_number": "NEW-1",
            "vendor": "DELL INC", "model": "R760",
        })
        self.assertEqual(row["vendor"], "Dell")
        self.assertEqual(row["equipment_type"], "Сервер")

        row = soft_receipt_source({
            "item_name": "Micron 7450 NVMe", "serial_number": "NEW-2",
        })
        self.assertEqual(row["vendor"], "Micron")
        self.assertEqual(row["component_type"], "SSD")


if __name__ == "__main__":
    unittest.main()
