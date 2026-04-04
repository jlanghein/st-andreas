"""Tests for SEPA transaction building and XML generation."""

from __future__ import annotations

from datetime import date

import pytest

from st_andreas.sepa.config import (
    BEITRAG_EUR,
    Beitragsstufe,
    CreditorConfig,
    SepaConfig,
)
from st_andreas.sepa.transactions import (
    MemberRecord,
    SepaTransaction,
    build_transactions,
)
from st_andreas.sepa.xml_generator import build_sepa_xml

TEST_CREDITOR = CreditorConfig(
    name="Test Creditor",
    iban="DE87200100200181044205",
    bic="PBNKDEFFXXX",
    creditor_id="DE07ZZZ00000461272",
)


class TestBeitragEur:
    def test_kinder_jugend_is_120(self) -> None:
        assert BEITRAG_EUR[Beitragsstufe.KINDER_JUGEND] == 120

    def test_erwachsene_is_120(self) -> None:
        assert BEITRAG_EUR[Beitragsstufe.ERWACHSENE] == 120

    def test_familie_is_180(self) -> None:
        assert BEITRAG_EUR[Beitragsstufe.FAMILIE] == 180

    def test_ermaessigt_is_24(self) -> None:
        assert BEITRAG_EUR[Beitragsstufe.ERMAESSIGT] == 24

    def test_unterstuetzend_is_120(self) -> None:
        assert BEITRAG_EUR[Beitragsstufe.UNTERSTUETZEND] == 120


class TestSepaConfigPaymentReference:
    def test_generates_reference_with_year_and_stufe(self) -> None:
        config = SepaConfig(
            collection_date=date(2025, 11, 15), year=2025, creditor=TEST_CREDITOR
        )
        ref = config.payment_reference(Beitragsstufe.KINDER_JUGEND)
        assert ref == "2025 Beitrag St-Andreas Stufe 1"

    def test_uses_stufe_value_in_reference(self) -> None:
        config = SepaConfig(
            collection_date=date(2025, 11, 15), year=2025, creditor=TEST_CREDITOR
        )
        ref = config.payment_reference(Beitragsstufe.FAMILIE)
        assert ref == "2025 Beitrag St-Andreas Stufe 3"


class TestBuildTransactions:
    @pytest.fixture
    def config(self) -> SepaConfig:
        return SepaConfig(
            collection_date=date(2025, 11, 15), year=2025, creditor=TEST_CREDITOR
        )

    def test_excludes_members_with_paid_beitrag(self, config: SepaConfig) -> None:
        member = MemberRecord(
            mitglieds_nr="AB123",
            familien_nr=None,
            vorname="Max",
            nachname="Mustermann",
            iban="DE89370400440532013000",
            bic="COBADEFFXXX",
            kontoinhaber="Max Mustermann",
            beitragsstufe=Beitragsstufe.KINDER_JUGEND,
            beitrag_bezahlt=True,
        )
        transactions, excluded = build_transactions([member], config)
        assert len(transactions) == 0
        assert len(excluded) == 0

    def test_excludes_members_without_iban(self, config: SepaConfig) -> None:
        member = MemberRecord(
            mitglieds_nr="AB123",
            familien_nr=None,
            vorname="Max",
            nachname="Mustermann",
            iban=None,
            bic=None,
            kontoinhaber=None,
            beitragsstufe=Beitragsstufe.KINDER_JUGEND,
            beitrag_bezahlt=False,
        )
        transactions, excluded = build_transactions([member], config)
        assert len(transactions) == 0
        assert excluded == [member]

    def test_excludes_members_without_beitragsstufe(self, config: SepaConfig) -> None:
        member = MemberRecord(
            mitglieds_nr="AB123",
            familien_nr=None,
            vorname="Max",
            nachname="Mustermann",
            iban="DE89370400440532013000",
            bic="COBADEFFXXX",
            kontoinhaber="Max Mustermann",
            beitragsstufe=None,
            beitrag_bezahlt=False,
        )
        transactions, excluded = build_transactions([member], config)
        assert len(transactions) == 0
        assert excluded == [member]

    def test_uses_kontoinhaber_as_debtor_name(self, config: SepaConfig) -> None:
        member = MemberRecord(
            mitglieds_nr="AB123",
            familien_nr=None,
            vorname="Max",
            nachname="Mustermann",
            iban="DE89370400440532013000",
            bic="COBADEFFXXX",
            kontoinhaber="Erika Mustermann",
            beitragsstufe=Beitragsstufe.KINDER_JUGEND,
            beitrag_bezahlt=False,
        )
        transactions, _ = build_transactions([member], config)
        assert transactions[0].debtor_name == "Erika Mustermann"

    def test_falls_back_to_vorname_nachname_when_kontoinhaber_empty(
        self, config: SepaConfig
    ) -> None:
        member = MemberRecord(
            mitglieds_nr="AB123",
            familien_nr=None,
            vorname="Max",
            nachname="Mustermann",
            iban="DE89370400440532013000",
            bic="COBADEFFXXX",
            kontoinhaber=None,
            beitragsstufe=Beitragsstufe.KINDER_JUGEND,
            beitrag_bezahlt=False,
        )
        transactions, _ = build_transactions([member], config)
        assert transactions[0].debtor_name == "Max Mustermann"

    def test_uses_mitglieds_nr_as_mandate_id_for_individuals(
        self, config: SepaConfig
    ) -> None:
        member = MemberRecord(
            mitglieds_nr="AB123",
            familien_nr="FAM456",
            vorname="Max",
            nachname="Mustermann",
            iban="DE89370400440532013000",
            bic="COBADEFFXXX",
            kontoinhaber="Max Mustermann",
            beitragsstufe=Beitragsstufe.KINDER_JUGEND,
            beitrag_bezahlt=False,
        )
        transactions, _ = build_transactions([member], config)
        assert transactions[0].mandate_id == "AB123"

    def test_uses_familien_nr_as_mandate_id_for_families(
        self, config: SepaConfig
    ) -> None:
        member = MemberRecord(
            mitglieds_nr="AB123",
            familien_nr="FAM456",
            vorname="Max",
            nachname="Mustermann",
            iban="DE89370400440532013000",
            bic="COBADEFFXXX",
            kontoinhaber="Max Mustermann",
            beitragsstufe=Beitragsstufe.FAMILIE,
            beitrag_bezahlt=False,
        )
        transactions, _ = build_transactions([member], config)
        assert transactions[0].mandate_id == "FAM456"

    def test_deduplicates_by_mandate_id(self, config: SepaConfig) -> None:
        member1 = MemberRecord(
            mitglieds_nr="AB123",
            familien_nr="FAM456",
            vorname="Max",
            nachname="Mustermann",
            iban="DE89370400440532013000",
            bic="COBADEFFXXX",
            kontoinhaber="Eltern Mustermann",
            beitragsstufe=Beitragsstufe.FAMILIE,
            beitrag_bezahlt=False,
        )
        member2 = MemberRecord(
            mitglieds_nr="CD789",
            familien_nr="FAM456",
            vorname="Lisa",
            nachname="Mustermann",
            iban="DE89370400440532013000",
            bic="COBADEFFXXX",
            kontoinhaber="Eltern Mustermann",
            beitragsstufe=Beitragsstufe.FAMILIE,
            beitrag_bezahlt=False,
        )
        transactions, _ = build_transactions([member1, member2], config)
        assert len(transactions) == 1

    def test_normalizes_iban_removes_spaces(self, config: SepaConfig) -> None:
        member = MemberRecord(
            mitglieds_nr="AB123",
            familien_nr=None,
            vorname="Max",
            nachname="Mustermann",
            iban="DE89 3704 0044 0532 0130 00",
            bic="COBADEFFXXX",
            kontoinhaber="Max Mustermann",
            beitragsstufe=Beitragsstufe.KINDER_JUGEND,
            beitrag_bezahlt=False,
        )
        transactions, _ = build_transactions([member], config)
        assert transactions[0].iban == "DE89370400440532013000"

    def test_calculates_correct_amount_for_stufe(self, config: SepaConfig) -> None:
        member = MemberRecord(
            mitglieds_nr="AB123",
            familien_nr=None,
            vorname="Max",
            nachname="Mustermann",
            iban="DE89370400440532013000",
            bic="COBADEFFXXX",
            kontoinhaber="Max Mustermann",
            beitragsstufe=Beitragsstufe.ERMAESSIGT,
            beitrag_bezahlt=False,
        )
        transactions, _ = build_transactions([member], config)
        assert transactions[0].amount_eur == 24


class TestBuildSepaXml:
    @pytest.fixture
    def config(self) -> SepaConfig:
        return SepaConfig(
            collection_date=date(2025, 11, 15),
            year=2025,
            creditor=TEST_CREDITOR,
        )

    def test_generates_valid_xml_structure(self, config: SepaConfig) -> None:
        transaction = SepaTransaction(
            mandate_id="AB123",
            debtor_name="Max Mustermann",
            iban="DE89370400440532013000",
            bic="COBADEFFXXX",
            amount_eur=120,
            payment_reference="2025 Beitrag St-Andreas Stufe 1",
        )

        xml_bytes = build_sepa_xml([transaction], config)
        xml_str = xml_bytes.decode("utf-8")

        assert "<?xml version=" in xml_str
        assert "urn:iso:std:iso:20022:tech:xsd:pain.008.001.02" in xml_str
        assert "<CstmrDrctDbtInitn>" in xml_str
        assert "<GrpHdr>" in xml_str
        assert "<PmtInf>" in xml_str
        assert "<DrctDbtTxInf>" in xml_str

    def test_includes_creditor_info(self, config: SepaConfig) -> None:
        transaction = SepaTransaction(
            mandate_id="AB123",
            debtor_name="Max Mustermann",
            iban="DE89370400440532013000",
            bic="COBADEFFXXX",
            amount_eur=120,
            payment_reference="2025 Beitrag St-Andreas Stufe 1",
        )

        xml_bytes = build_sepa_xml([transaction], config)
        xml_str = xml_bytes.decode("utf-8")

        assert TEST_CREDITOR.iban in xml_str
        assert TEST_CREDITOR.bic in xml_str
        assert TEST_CREDITOR.creditor_id in xml_str

    def test_includes_transaction_details(self, config: SepaConfig) -> None:
        transaction = SepaTransaction(
            mandate_id="AB123",
            debtor_name="Max Mustermann",
            iban="DE89370400440532013000",
            bic="COBADEFFXXX",
            amount_eur=120,
            payment_reference="2025 Beitrag St-Andreas Stufe 1",
        )

        xml_bytes = build_sepa_xml([transaction], config)
        xml_str = xml_bytes.decode("utf-8")

        assert "<MndtId>AB123</MndtId>" in xml_str
        assert "DE89370400440532013000" in xml_str
        assert "<InstdAmt Ccy=" in xml_str and ">120<" in xml_str

    def test_calculates_correct_totals(self, config: SepaConfig) -> None:
        transactions = [
            SepaTransaction(
                mandate_id="AB123",
                debtor_name="Max Mustermann",
                iban="DE89370400440532013000",
                bic=None,
                amount_eur=120,
                payment_reference="ref1",
            ),
            SepaTransaction(
                mandate_id="CD456",
                debtor_name="Erika Musterfrau",
                iban="DE89370400440532013001",
                bic=None,
                amount_eur=180,
                payment_reference="ref2",
            ),
        ]

        xml_bytes = build_sepa_xml(transactions, config)
        xml_str = xml_bytes.decode("utf-8")

        assert "<NbOfTxs>2</NbOfTxs>" in xml_str
        assert "<CtrlSum>300</CtrlSum>" in xml_str

    def test_sanitizes_special_characters(self, config: SepaConfig) -> None:
        transaction = SepaTransaction(
            mandate_id="AB123",
            debtor_name="Müller & Söhne GmbH",
            iban="DE89370400440532013000",
            bic=None,
            amount_eur=120,
            payment_reference="Test",
        )

        xml_bytes = build_sepa_xml([transaction], config)
        xml_str = xml_bytes.decode("utf-8")

        assert "Mller  Shne GmbH" in xml_str
