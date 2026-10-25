"""The 60 invoice specifications, planted errors and edge cases (PLAN section 15). Single source of truth.

Each `InvoiceSpec` says what the invoice looks like, how it is recorded in the ledgers, which error
(if any) was planted, and what result the audit tests must give. The renderers, the ledger writer and
the answer key are all generated from these specs, so they can never disagree with each other.
"""

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from invoice_audit.money import quantize
from invoice_audit.synthetic.entities import (
    CATEGORY_CODE,
    COMPANY,
    DIRECTOR_PERSONAL,
    GROUP_COMPANY,
    SUPPLIERS,
    UNRELATED_COMPANY,
    Supplier,
)

FY_START = date(2025, 4, 1)
FY_END = date(2026, 3, 31)
POST_YE_END = date(2026, 6, 30)

LINE_POOLS = {
    "lumen": ["Tri-fold product brochures x 2,000", "Pull-up banner stands x 2", "Business cards x 500",
              "A5 product flyers x 5,000", "Design and artwork", "Exhibition graphics panels"],
    "carter": ["Accountancy services", "Payroll advice", "VAT return review", "Management accounts support"],
    "oakridge": ["Rent, Unit 4 Ferrow Lane", "Service charge"],
    "greenline": ["Electricity supply, workshop meter", "Standing charge", "Climate change levy"],
    "stackwise": ["Cloud ERP subscription (25 users)", "IT support retainer", "Endpoint security licences x 30",
                  "Laptop docking stations x 4"],
    "meridian": ["Return rail travel Halbridge to London", "Hotel accommodation, 2 nights",
                 "Flights Manchley to Hamburg, return"],
    "fixwell": ["Boiler annual service", "Repair to roller shutter door", "Replacement LED fittings, workshop",
                "Roof leak repair, bay 2"],
    "pemberton": ["Mild steel bar EN3B 50mm x 6m", "Stainless sheet 304 2mm", "Aluminium plate 6082 10mm",
                  "Cutting charges"],
    "harbour": ["A4 copier paper (box of 5 reams) x 10", "Toner cartridges x 4", "Archive boxes x 50",
                "Desk organisers x 6"],
    "kestrel": ["Combined commercial insurance premium", "Engineering inspection cover"],
    "atlas": ["Pillar drill, floor standing", "Bench grinder 200mm"],
    "bauer": ["Hydraulic coupling HK-220 x 40", "Bearing housing BG-75 x 120", "Seal kits x 200"],
    "summit": ["Cloud hosting, standard plan", "Data backup storage 2TB"],
}  # fmt: skip


@dataclass
class InvoiceSpec:
    test: str  # "main" or "cutoff"
    supplier: Supplier
    invoice_date: date
    lines: list[tuple[str, Decimal]]
    category: str
    addressed_to: str = COMPANY
    invoice_number: str = ""  # filled from the supplier's numbering unless set
    description: str = ""  # one-line summary (the truth for the description field)
    period_basis: str = "not_determinable"
    service_period: tuple[date, date] | None = None
    delivery_date: date | None = None
    period_note: str | None = None  # extra line printed on the invoice, e.g. a delivery note reference
    # ---- how it is recorded
    recorded_in: str = "current"  # current / post_ye / both / neither
    posting_date: date | None = None
    post_ye_posting_date: date | None = None  # only for "both"
    ledger_number: str | None = None  # how the ledger writes the invoice number, if different
    ledger_code: str | None = None  # nominal code, if posted to the wrong one
    ledger_net: Decimal | None = None  # net amount in the ledger, if wrong
    ledger_gbp_net: Decimal | None = None  # sterling net for foreign-currency invoices
    ledger_original: Decimal | None = None  # original-currency amount in the ledger
    # ---- expectations
    planted_errors: list[str] = field(default_factory=list)
    expected_checks: dict[str, str] = field(default_factory=dict)
    expected_overall: str | None = None
    expected_adjustment: Decimal | None = None
    # ---- rendering (assigned later)
    invoice_id: str = ""
    format: str = ""
    file: str = ""
    attachment: str | None = None
    layout: int = 0

    @property
    def currency(self) -> str:
        return self.supplier.currency

    @property
    def net(self) -> Decimal:
        return sum((amount for _, amount in self.lines), Decimal("0.00"))

    @property
    def vat(self) -> Decimal:
        return quantize(self.net * self.supplier.vat_rate / 100)

    @property
    def gross(self) -> Decimal:
        return self.net + self.vat

    @property
    def due_date(self) -> date:
        return self.invoice_date + timedelta(days=30)

    def overall(self) -> str:
        if self.expected_overall:
            return self.expected_overall
        statuses = set(self.expected_checks.values())
        for status in ("exception", "review"):
            if status in statuses:
                return status
        return "pass"


# ---------------------------------------------------------------- helpers


class _Numbering:
    """Per-supplier invoice numbers that never repeat (filler ledger lines use the same counters)."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.next = {key: rng.randint(1200, 8000) for key in SUPPLIERS}
        self.next["harbour"] = rng.randint(3000, 3500)  # keeps clear of the planted "INV2231"
        self.used: set[str] = {"INV2231"}

    def number(self, supplier: Supplier, when: date) -> str:
        while True:
            self.next[supplier.key] += self.rng.randint(3, 40)
            n = self.next[supplier.key]
            text = supplier.number_format.format(n=n, yy=f"{when:%y}", yyyy=f"{when:%Y}")
            if text not in self.used:
                self.used.add(text)
                return text


def _amount(rng: random.Random, low: int, high: int) -> Decimal:
    whole = rng.randint(low, high)
    pence = 0 if rng.random() < 0.4 else rng.randint(1, 99)
    return Decimal(whole) + Decimal(pence) / 100


def _lines(rng: random.Random, supplier: Supplier, total: Decimal | None = None) -> list[tuple[str, Decimal]]:
    """1-3 line items from the supplier's pool, adding up to `total` (or a random total in its range)."""
    total = total if total is not None else _amount(rng, *supplier.amount_range)
    pool = LINE_POOLS[supplier.key]
    count = min(len(pool), rng.choice([1, 1, 2, 2, 3]))
    descriptions = rng.sample(pool, count)
    if count == 1:
        return [(descriptions[0], total)]
    shares = [Decimal(rng.randint(20, 60)) for _ in range(count)]
    parts = [quantize(total * share / sum(shares)) for share in shares[:-1]]
    parts.append(total - sum(parts))
    return list(zip(descriptions, parts, strict=True))


def _date_in(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


def _posting(rng: random.Random, invoice_date: date, latest: date = FY_END) -> date:
    return min(invoice_date + timedelta(days=rng.randint(1, 12)), latest)


ALL_PASS_MAIN = {"A": "pass", "D": "pass", "E": "pass", "C": "pass"}
ALL_PASS_CUTOFF = {"A": "pass", "P": "pass"}


def _main(
    rng: random.Random, key: str, errors: list[str] | None = None, checks: dict | None = None, **kw
) -> InvoiceSpec:
    supplier = SUPPLIERS[key]
    invoice_date = kw.pop("invoice_date", None) or _date_in(rng, FY_START, FY_END - timedelta(days=14))
    lines = kw.pop("lines", None) or _lines(rng, supplier, kw.pop("total", None))
    spec = InvoiceSpec(
        test="main",
        supplier=supplier,
        invoice_date=invoice_date,
        lines=lines,
        category=kw.pop("category", supplier.category),
        planted_errors=errors or [],
        expected_checks={**ALL_PASS_MAIN, **(checks or {})},
        **kw,
    )
    spec.description = spec.description or "; ".join(d for d, _ in lines)
    spec.posting_date = spec.posting_date or _posting(rng, invoice_date)
    return spec


def _cutoff(key: str, invoice_date: date, lines: list[tuple[str, Decimal]], errors: list[str] | None = None,
            checks: dict | None = None, **kw) -> InvoiceSpec:  # fmt: skip
    supplier = SUPPLIERS[key]
    spec = InvoiceSpec(
        test="cutoff",
        supplier=supplier,
        invoice_date=invoice_date,
        lines=lines,
        category=kw.pop("category", supplier.category),
        planted_errors=errors or [],
        expected_checks={**ALL_PASS_CUTOFF, **(checks or {})},
        **kw,
    )
    spec.description = spec.description or "; ".join(d for d, _ in lines)
    return spec


def d(text: str) -> date:
    return date.fromisoformat(text)


def D(text: str) -> Decimal:
    return Decimal(text)


# ---------------------------------------------------------------- the main sample (35)


def main_sample(rng: random.Random) -> list[InvoiceSpec]:
    specs = [
        # --- planted errors (16)
        _main(rng, "pemberton", ["E01"], {"A": "exception"}, lines=[("Mild steel bar EN3B 50mm x 6m", D("1243.50"))],
              ledger_net=D("1234.50")),
        _main(rng, "fixwell", ["E02"], {"A": "exception"}, lines=[("Repair to roller shutter door", D("845.00"))],
              ledger_net=D("1014.00")),  # gross posted in the net column
        _main(rng, "stackwise", ["E03"], {"A": "exception"},
              lines=[("Cloud ERP subscription (25 users), annual", D("4850.00"))], ledger_net=D("4580.00")),
        _main(rng, "harbour", ["E04"], {"A": "exception"},
              lines=[("Toner cartridges x 4", D("412.35")), ("Archive boxes x 50", D("200.00"))],
              ledger_net=D("612.34")),
        _main(rng, "carter", ["E05"], {"D": "exception"}, invoice_date=d("2025-02-15"),
              lines=[("Year-end accounts preparation", D("2400.00"))], posting_date=d("2025-04-08")),
        _main(rng, "meridian", ["E06"], {"D": "exception"}, invoice_date=d("2026-05-12"),
              lines=[("Flights Manchley to Hamburg, return", D("486.20"))], posting_date=d("2026-03-31")),
        _main(rng, "greenline", ["E07"], {"D": "exception"}, invoice_date=d("2025-03-31"),
              lines=[("Electricity supply, workshop meter", D("1876.40"))], posting_date=d("2025-04-02")),
        _main(rng, "oakridge", ["E08"], {"E": "exception"}, addressed_to=GROUP_COMPANY),
        _main(rng, "harbour", ["E09"], {"E": "exception"}, addressed_to=UNRELATED_COMPANY),
        _main(rng, "meridian", ["E10"], {"E": "exception"}, addressed_to=DIRECTOR_PERSONAL),
        _main(rng, "lumen", ["E11"], {"C": "exception"},
              lines=[("Exhibition stand hire, Northern Engineering Expo", D("2150.00")),
                     ("Product brochures x 1,500", D("640.00"))],
              description="Exhibition stand hire and brochures", ledger_code="6800"),
        _main(rng, "atlas", ["E12"], {"C": "exception"}, lines=[("New CNC lathe, model TL-300", D("18500.00"))],
              ledger_code="6700"),
        _main(rng, "carter", ["E13"], {"C": "exception"},
              lines=[("Legal fees: review of new lease, Unit 4 Ferrow Lane", D("1650.00"))],
              category="Professional fees", ledger_code="6800"),
        _main(rng, "greenline", ["E14"], {"C": "exception"}, ledger_code="6300"),
        _main(rng, "pemberton", ["E15"], {"A": "n/a", "D": "n/a", "E": "n/a", "C": "n/a"},
              expected_overall="exception", recorded_in="neither"),
        _main(rng, "bauer", ["E16"], {"A": "exception"}, lines=[("Hydraulic coupling HK-220 x 40", D("3200.00"))],
              ledger_original=D("3020.00"), ledger_gbp_net=D("2737.88")),
        # --- clean controls that must pass (19)
        _main(rng, "pemberton", invoice_date=FY_START),  # first day of the FY
        _main(rng, "harbour", invoice_date=FY_END, posting_date=FY_END),  # last day of the FY
        _main(rng, "stackwise", addressed_to="BRACKENFIELD ENGINEERING LIMITED"),
        _main(rng, "fixwell", addressed_to="Brackenfield Engineering Ltd."),
        _main(rng, "meridian", addressed_to="Brackenfield Precision"),  # trading name (alias)
        _main(rng, "oakridge", addressed_to="Brackenfeild Engineering Ltd"),  # typo, fuzzy score >= 92
        _main(rng, "summit", lines=[("Cloud hosting, standard plan", D("1250.00"))],
              ledger_original=D("1250.00"), ledger_gbp_net=D("987.36")),
        _main(rng, "harbour", invoice_number="INV2231", ledger_number="inv 2231"),  # spacing/case differ
        _main(rng, "kestrel"),
        _main(rng, "carter"),
        _main(rng, "greenline", lines=[("Gas supply, offices", D("742.18"))]),
        _main(rng, "lumen"),
        _main(rng, "pemberton"),
        _main(rng, "bauer", lines=[("Bearing housing BG-75 x 120", D("2160.00"))], ledger_original=D("2160.00"),
              ledger_gbp_net=D("1847.81")),
        _main(rng, "atlas", lines=[("Pillar drill, floor standing", D("6890.00"))]),
        _main(rng, "stackwise"),
        _main(rng, "meridian"),
        _main(rng, "fixwell"),
        _main(rng, "carter", lines=[("Recruitment fee: CNC machinist placement", D("3200.00"))]),
    ]  # fmt: skip
    return specs


# ---------------------------------------------------------------- the cut-off sample (25)


def cutoff_sample() -> list[InvoiceSpec]:
    explicit = "explicit_period"
    specs = [
        # --- planted errors and judgement items (12)
        _cutoff("carter", d("2026-04-10"), [("Consultancy services – March 2026", D("3600.00"))], ["C01"],
                {"P": "exception"}, period_basis=explicit, service_period=(d("2026-03-01"), d("2026-03-31")),
                recorded_in="post_ye", posting_date=d("2026-04-15")),
        _cutoff("pemberton", d("2026-04-02"), [("Stainless sheet 304 2mm", D("4275.60"))], ["C02"],
                {"P": "exception"}, period_basis="delivery_date", delivery_date=d("2026-03-28"),
                period_note="Goods delivered 28/03/2026, delivery note DN-48213", recorded_in="post_ye",
                posting_date=d("2026-04-07")),
        _cutoff("fixwell", d("2026-04-06"), [("Repairs carried out 24–26 March 2026, press shop", D("1385.00"))],
                ["C03"], {"P": "exception"}, period_basis=explicit,
                service_period=(d("2026-03-24"), d("2026-03-26")), recorded_in="post_ye",
                posting_date=d("2026-04-09")),
        _cutoff("stackwise", d("2026-03-25"), [("Annual software licence 01/04/2026–31/03/2027", D("5400.00"))],
                ["C04"], {"P": "exception"}, period_basis=explicit,
                service_period=(d("2026-04-01"), d("2027-03-31")), posting_date=d("2026-03-27")),
        _cutoff("oakridge", d("2026-03-25"), [("Rent for April 2026 in advance", D("6250.00"))], ["C05"],
                {"P": "exception"}, period_basis=explicit, service_period=(d("2026-04-01"), d("2026-04-30")),
                posting_date=d("2026-03-26")),
        _cutoff("lumen", d("2026-03-20"),
                [("Trade show sponsorship, Northern Engineering Expo, event 14 May 2026", D("2500.00"))], ["C06"],
                {"P": "exception"}, period_basis=explicit, service_period=(d("2026-05-14"), d("2026-05-14")),
                posting_date=d("2026-03-23")),
        _cutoff("kestrel", d("2025-12-18"),
                [("Combined commercial insurance, policy period 01/01/2026–31/12/2026", D("3650.00"))], ["C07"],
                {"P": "review"}, period_basis=explicit, service_period=(d("2026-01-01"), d("2026-12-31")),
                posting_date=d("2026-01-05"), expected_adjustment=D("2750.00")),
        _cutoff("fixwell", d("2026-04-08"),
                [("Planned maintenance contract 01/02/2026–31/05/2026", D("2400.00"))], ["C08"], {"P": "review"},
                period_basis=explicit, service_period=(d("2026-02-01"), d("2026-05-31")), recorded_in="post_ye",
                posting_date=d("2026-04-14"), expected_adjustment=D("1180.00"),
                category="Repairs & maintenance"),
        _cutoff("harbour", d("2026-01-05"), [("Office cleaning services, Q1 and April 2026", D("1800.00"))],
                ["C09"], {"P": "review"}, period_basis="description_inference",
                service_period=(d("2026-01-01"), d("2026-04-30")), posting_date=d("2026-01-09"),
                expected_adjustment=D("450.00")),
        _cutoff("carter", d("2026-03-03"), [("Consultancy services – February 2026", D("2850.00"))], ["C10"],
                {"A": "n/a", "P": "exception"}, period_basis=explicit,
                service_period=(d("2026-02-01"), d("2026-02-28")), recorded_in="neither"),
        _cutoff("greenline", d("2026-03-12"), [("Electricity supply, workshop meter, February 2026", D("2213.75"))],
                ["C11"], {"P": "exception"}, period_basis=explicit,
                service_period=(d("2026-02-01"), d("2026-02-28")), recorded_in="both",
                posting_date=d("2026-03-16"), post_ye_posting_date=d("2026-04-08")),
        _cutoff("harbour", d("2026-03-30"), [("A4 copier paper (box of 5 reams) x 10", D("189.90")),
                                             ("Desk organisers x 6", D("74.40"))], ["C12"], {"P": "review"},
                posting_date=d("2026-03-31")),
        # --- clean: pre-YE recorded in the current year (7)
        _cutoff("pemberton", d("2026-03-20"), [("Aluminium plate 6082 10mm", D("3318.00"))],
                period_basis="delivery_date", delivery_date=d("2026-03-20"),
                period_note="Delivered 20/03/2026", posting_date=d("2026-03-23")),
        _cutoff("carter", d("2026-03-02"), [("Audit preparation support – February 2026", D("1950.00"))],
                period_basis=explicit, service_period=(d("2026-02-01"), d("2026-02-28")),
                posting_date=d("2026-03-05")),
        _cutoff("greenline", d("2026-03-06"), [("Electricity supply 01/02/2026–28/02/2026", D("2087.31"))],
                period_basis=explicit, service_period=(d("2026-02-01"), d("2026-02-28")),
                posting_date=d("2026-03-10")),
        _cutoff("stackwise", d("2026-03-31"), [("IT support retainer – March 2026", D("950.00"))],
                period_basis=explicit, service_period=(d("2026-03-01"), d("2026-03-31")), posting_date=FY_END),
        _cutoff("fixwell", d("2026-04-03"), [("Plant servicing completed March 2026", D("1120.00"))],
                period_basis=explicit, service_period=(d("2026-03-01"), d("2026-03-31")),
                posting_date=FY_END),  # March work, invoiced in April, correctly accrued in the current year
        _cutoff("harbour", d("2026-03-27"), [("Archive boxes x 50", D("142.50"))], period_basis="delivery_date",
                delivery_date=d("2026-03-27"), period_note="Delivered 27/03/2026", posting_date=d("2026-03-30")),
        _cutoff("meridian", d("2026-03-20"), [("Hotel accommodation, 16–18 March 2026", D("412.80"))],
                period_basis=explicit, service_period=(d("2026-03-16"), d("2026-03-18")),
                posting_date=d("2026-03-25")),
        # --- clean: post-YE recorded in the post-YE ledger (6)
        _cutoff("oakridge", d("2026-04-01"), [("Rent, quarter 1 April 2026 to 30 June 2026", D("18750.00"))],
                period_basis=explicit, service_period=(d("2026-04-01"), d("2026-06-30")), recorded_in="post_ye",
                posting_date=d("2026-04-02")),
        _cutoff("greenline", d("2026-05-06"), [("Electricity supply, April 2026", D("1964.08"))],
                period_basis=explicit, service_period=(d("2026-04-01"), d("2026-04-30")), recorded_in="post_ye",
                posting_date=d("2026-05-08")),
        _cutoff("pemberton", d("2026-04-08"), [("Mild steel bar EN3B 50mm x 6m", D("2846.40"))],
                period_basis="delivery_date", delivery_date=d("2026-04-08"), period_note="Delivered 08/04/2026",
                recorded_in="post_ye", posting_date=d("2026-04-10")),
        _cutoff("lumen", d("2026-04-15"), [("A5 product flyers x 5,000", D("585.00"))],
                period_basis="delivery_date", delivery_date=d("2026-04-15"), period_note="Delivered 15/04/2026",
                recorded_in="post_ye", posting_date=d("2026-04-20")),
        _cutoff("carter", d("2026-05-01"), [("Tax advisory – April 2026", D("1450.00"))], period_basis=explicit,
                service_period=(d("2026-04-01"), d("2026-04-30")), recorded_in="post_ye",
                posting_date=d("2026-05-05")),
        _cutoff("stackwise", d("2026-05-01"), [("Cloud ERP subscription – May 2026", D("780.00"))],
                period_basis=explicit, service_period=(d("2026-05-01"), d("2026-05-31")), recorded_in="post_ye",
                posting_date=d("2026-05-04")),
    ]  # fmt: skip
    return specs


# ---------------------------------------------------------------- formats, ids and file names

MAIN_FORMATS = (["digital_pdf"] * 10 + ["scanned_pdf"] * 6 + ["jpg_photo"] * 4 + ["png_scan"] * 3 + ["docx"] * 4
                + ["xlsx"] * 3 + ["email_pdf"] * 2 + ["email_jpg"] * 1 + ["email_pair"] * 2)  # fmt: skip
CUTOFF_FORMATS = (["digital_pdf"] * 7 + ["scanned_pdf"] * 4 + ["jpg_photo"] * 2 + ["png_scan"] * 3 + ["docx"] * 2
                  + ["xlsx"] * 3 + ["email_pdf"] * 1 + ["email_jpg"] * 2 + ["email_body"] * 1)  # fmt: skip
EXTENSIONS = {"digital_pdf": "pdf", "scanned_pdf": "pdf", "jpg_photo": "jpg", "png_scan": "png", "docx": "docx",
              "xlsx": "xlsx"}  # fmt: skip


def _assign_files(specs: list[InvoiceSpec], formats: list[str], folder: str, prefix: str, rng: random.Random,
                  first_number: int, emails_before: int) -> None:  # fmt: skip
    """File names are unique across both folders (main doc_001.., cut-off doc_101..), so a name on the
    workpaper always points to exactly one file."""
    rng.shuffle(specs)
    formats = list(formats)
    rng.shuffle(formats)
    email_count = emails_before
    pair_file = None
    for index, (spec, fmt) in enumerate(zip(specs, formats, strict=True), start=1):
        position = first_number + index - 1
        spec.invoice_id = f"INV-{prefix}-{index:03d}"
        spec.layout = rng.randint(0, 3)
        if fmt == "email_pair":
            if pair_file is None:
                email_count += 1
                pair_file = f"{folder}/email_{email_count:02d}.eml"
            spec.format, spec.file = "email_pdf", pair_file
            spec.attachment = f"{spec.invoice_number.replace('/', '-')}.pdf"
        elif fmt.startswith("email_"):
            email_count += 1
            spec.format, spec.file = fmt, f"{folder}/email_{email_count:02d}.eml"
            if fmt != "email_body":
                spec.attachment = f"{spec.invoice_number.replace('/', '-')}.{fmt.split('_')[1]}"
        else:
            stem = {"jpg_photo": "photo", "png_scan": "scan"}.get(fmt, "doc")
            spec.format, spec.file = fmt, f"{folder}/{stem}_{position:03d}.{EXTENSIONS[fmt]}"


@dataclass
class Scenario:
    seed: int
    invoices: list[InvoiceSpec]
    blurry: InvoiceSpec  # edge case: heavily blurred photo, must come out as needs_review
    statement_supplier: Supplier
    numbering: "_Numbering"
    rng: random.Random


def build_scenario(seed: int) -> Scenario:
    rng = random.Random(seed)
    numbering = _Numbering(rng)
    main = main_sample(rng)
    cutoff = cutoff_sample()
    blurry = _main(rng, "harbour", lines=[("Desk organisers x 6", D("74.40")), ("Toner cartridges x 2", D("96.00"))],
                   invoice_date=d("2025-09-17"))  # fmt: skip
    for spec in [*main, *cutoff, blurry]:
        if not spec.invoice_number:
            spec.invoice_number = numbering.number(spec.supplier, spec.invoice_date)
        if spec.recorded_in in ("current", "both") and spec.posting_date is None:
            spec.posting_date = _posting(rng, spec.invoice_date)
    # C11: the same invoice number in both ledgers is the planted error, so nothing else to change.
    _assign_files(main, MAIN_FORMATS, "main_sample", "M", rng, first_number=1, emails_before=0)
    _assign_files(cutoff, CUTOFF_FORMATS, "cutoff_sample", "C", rng, first_number=101, emails_before=4)
    blurry.invoice_id, blurry.format, blurry.file, blurry.layout = (
        "EDGE-BLURRY",
        "jpg_photo",
        "main_sample/blurry_receipt.jpg",
        0,
    )
    return Scenario(seed, [*main, *cutoff], blurry, SUPPLIERS["pemberton"], numbering, rng)


def ledger_code(spec: InvoiceSpec) -> str:
    return spec.ledger_code or CATEGORY_CODE[spec.category]
