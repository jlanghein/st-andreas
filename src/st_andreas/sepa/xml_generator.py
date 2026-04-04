"""SEPA pain.008.001.02 XML generation."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, cast

from lxml import etree

if TYPE_CHECKING:
    from lxml.etree import _Element

from st_andreas.sepa.config import SepaConfig
from st_andreas.sepa.transactions import SepaTransaction

SEPA_NAMESPACE: Final[str] = "urn:iso:std:iso:20022:tech:xsd:pain.008.001.02"
XSI_NAMESPACE: Final[str] = "http://www.w3.org/2001/XMLSchema-instance"
XSD_NAMESPACE: Final[str] = "http://www.w3.org/2001/XMLSchema"

SEPA_CHARSET_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^a-zA-Z0-9 /:?\-().,'+]")

PAYMENT_METHOD_DIRECT_DEBIT: Final[str] = "DD"
SERVICE_LEVEL_SEPA: Final[str] = "SEPA"
LOCAL_INSTRUMENT_CORE: Final[str] = "CORE"
SEQUENCE_TYPE_RECURRING: Final[str] = "RCUR"
CHARGE_BEARER_SLEV: Final[str] = "SLEV"
CURRENCY_EUR: Final[str] = "EUR"
END_TO_END_ID_NOT_PROVIDED: Final[str] = "NOTPROVIDED"
DEBTOR_AGENT_NOT_PROVIDED: Final[str] = "NOTPROVIDED"


def build_sepa_xml(
    transactions: list[SepaTransaction],
    config: SepaConfig,
) -> bytes:
    """Generate SEPA pain.008.001.02 XML for direct debit batch."""
    # lxml supports None as key for default namespace, but stubs don't reflect this
    nsmap = {
        "xsi": XSI_NAMESPACE,
        "xsd": XSD_NAMESPACE,
        None: SEPA_NAMESPACE,
    }

    root: Any = etree.Element("Document", nsmap=cast(Any, nsmap))
    initiation = etree.SubElement(root, "CstmrDrctDbtInitn")

    _build_group_header(initiation, transactions, config)
    _build_payment_info(initiation, transactions, config)

    return etree.tostring(
        root,
        pretty_print=True,
        encoding="utf-8",
        xml_declaration=True,
    )


def _build_group_header(
    parent: _Element,
    transactions: list[SepaTransaction],
    config: SepaConfig,
) -> None:
    """Build GrpHdr element."""
    grp_hdr = etree.SubElement(parent, "GrpHdr")

    etree.SubElement(grp_hdr, "MsgId").text = uuid.uuid4().hex.upper()
    etree.SubElement(grp_hdr, "CreDtTm").text = datetime.now().isoformat()
    etree.SubElement(grp_hdr, "NbOfTxs").text = str(len(transactions))
    etree.SubElement(grp_hdr, "CtrlSum").text = str(_calculate_total(transactions))

    initg_pty = etree.SubElement(grp_hdr, "InitgPty")
    etree.SubElement(initg_pty, "Nm").text = _sanitize_sepa_string(config.creditor.name)


def _build_payment_info(
    parent: _Element,
    transactions: list[SepaTransaction],
    config: SepaConfig,
) -> None:
    """Build PmtInf element with all transactions."""
    pmt_inf = etree.SubElement(parent, "PmtInf")

    etree.SubElement(pmt_inf, "PmtInfId").text = uuid.uuid4().hex.upper()
    etree.SubElement(pmt_inf, "PmtMtd").text = PAYMENT_METHOD_DIRECT_DEBIT
    etree.SubElement(pmt_inf, "BtchBookg").text = "true"
    etree.SubElement(pmt_inf, "NbOfTxs").text = str(len(transactions))
    etree.SubElement(pmt_inf, "CtrlSum").text = str(_calculate_total(transactions))

    _build_payment_type_info(pmt_inf)

    etree.SubElement(pmt_inf, "ReqdColltnDt").text = config.collection_date.strftime(
        "%Y-%m-%d"
    )

    _build_creditor_info(pmt_inf, config)

    for transaction in transactions:
        _build_transaction_info(pmt_inf, transaction, config)


def _build_payment_type_info(parent: _Element) -> None:
    """Build PmtTpInf element."""
    pmt_tp_inf = etree.SubElement(parent, "PmtTpInf")

    svc_lvl = etree.SubElement(pmt_tp_inf, "SvcLvl")
    etree.SubElement(svc_lvl, "Cd").text = SERVICE_LEVEL_SEPA

    lcl_instrm = etree.SubElement(pmt_tp_inf, "LclInstrm")
    etree.SubElement(lcl_instrm, "Cd").text = LOCAL_INSTRUMENT_CORE

    etree.SubElement(pmt_tp_inf, "SeqTp").text = SEQUENCE_TYPE_RECURRING


def _build_creditor_info(parent: _Element, config: SepaConfig) -> None:
    """Build creditor-related elements (Cdtr, CdtrAcct, CdtrAgt)."""
    cdtr = etree.SubElement(parent, "Cdtr")
    etree.SubElement(cdtr, "Nm").text = _sanitize_sepa_string(config.creditor.name)

    cdtr_acct = etree.SubElement(parent, "CdtrAcct")
    cdtr_acct_id = etree.SubElement(cdtr_acct, "Id")
    etree.SubElement(cdtr_acct_id, "IBAN").text = config.creditor.iban
    etree.SubElement(cdtr_acct, "Ccy").text = CURRENCY_EUR

    cdtr_agt = etree.SubElement(parent, "CdtrAgt")
    fin_instn_id = etree.SubElement(cdtr_agt, "FinInstnId")
    etree.SubElement(fin_instn_id, "BIC").text = config.creditor.bic

    etree.SubElement(parent, "ChrgBr").text = CHARGE_BEARER_SLEV


def _build_transaction_info(
    parent: _Element,
    transaction: SepaTransaction,
    config: SepaConfig,
) -> None:
    """Build DrctDbtTxInf element for a single transaction."""
    tx_inf = etree.SubElement(parent, "DrctDbtTxInf")

    pmt_id = etree.SubElement(tx_inf, "PmtId")
    etree.SubElement(pmt_id, "EndToEndId").text = END_TO_END_ID_NOT_PROVIDED

    instd_amt = etree.SubElement(tx_inf, "InstdAmt", Ccy=CURRENCY_EUR)
    instd_amt.text = str(transaction.amount_eur)

    _build_direct_debit_tx(tx_inf, transaction, config)
    _build_debtor_agent(tx_inf)
    _build_debtor_info(tx_inf, transaction)
    _build_remittance_info(tx_inf, transaction)


def _build_direct_debit_tx(
    parent: _Element,
    transaction: SepaTransaction,
    config: SepaConfig,
) -> None:
    """Build DrctDbtTx element with mandate info."""
    drct_dbt_tx = etree.SubElement(parent, "DrctDbtTx")

    mndt_rltd_inf = etree.SubElement(drct_dbt_tx, "MndtRltdInf")
    etree.SubElement(mndt_rltd_inf, "MndtId").text = transaction.mandate_id
    etree.SubElement(mndt_rltd_inf, "DtOfSgntr").text = datetime.now().strftime(
        "%Y-%m-%d"
    )

    cdtr_schme_id = etree.SubElement(drct_dbt_tx, "CdtrSchmeId")
    schme_id = etree.SubElement(cdtr_schme_id, "Id")
    prvt_id = etree.SubElement(schme_id, "PrvtId")
    othr = etree.SubElement(prvt_id, "Othr")
    etree.SubElement(othr, "Id").text = config.creditor.creditor_id
    schme_nm = etree.SubElement(othr, "SchmeNm")
    etree.SubElement(schme_nm, "Prtry").text = SERVICE_LEVEL_SEPA


def _build_debtor_agent(parent: _Element) -> None:
    """Build DbtrAgt element."""
    dbtr_agt = etree.SubElement(parent, "DbtrAgt")
    fin_instn_id = etree.SubElement(dbtr_agt, "FinInstnId")
    othr = etree.SubElement(fin_instn_id, "Othr")
    etree.SubElement(othr, "Id").text = DEBTOR_AGENT_NOT_PROVIDED


def _build_debtor_info(
    parent: _Element,
    transaction: SepaTransaction,
) -> None:
    """Build Dbtr and DbtrAcct elements."""
    dbtr = etree.SubElement(parent, "Dbtr")
    etree.SubElement(dbtr, "Nm").text = _sanitize_sepa_string(transaction.debtor_name)

    dbtr_acct = etree.SubElement(parent, "DbtrAcct")
    dbtr_acct_id = etree.SubElement(dbtr_acct, "Id")
    etree.SubElement(dbtr_acct_id, "IBAN").text = transaction.iban


def _build_remittance_info(
    parent: _Element,
    transaction: SepaTransaction,
) -> None:
    """Build RmtInf element."""
    rmt_inf = etree.SubElement(parent, "RmtInf")
    etree.SubElement(rmt_inf, "Ustrd").text = _sanitize_sepa_string(
        transaction.payment_reference
    )


def _calculate_total(transactions: list[SepaTransaction]) -> int:
    """Calculate total amount of all transactions."""
    return sum(t.amount_eur for t in transactions)


def _sanitize_sepa_string(text: str) -> str:
    """Remove characters not allowed in SEPA XML fields."""
    return SEPA_CHARSET_PATTERN.sub("", text)
