"""The fictional audited company, its group, suppliers and chart of accounts.

Fictional entities. Any resemblance to real organisations is coincidental.
"""

from dataclasses import dataclass
from decimal import Decimal

COMPANY = "Brackenfield Engineering Ltd"
COMPANY_ADDRESS = ["Unit 4, Ferrow Lane Industrial Estate", "Halbridge", "West Yorkshire", "HX7 4QD"]
GROUP_COMPANY = "Brackenfield Holdings Ltd"
GROUP_ADDRESS = ["2 Mercer Court", "Halbridge", "West Yorkshire", "HX7 1AB"]
UNRELATED_COMPANY = "Calder Mill Catering Ltd"
UNRELATED_ADDRESS = ["The Old Mill, Wharf Street", "Sowerdale", "West Yorkshire", "HX6 2LP"]
DIRECTOR_PERSONAL = "Mr J Brackenfield"
DIRECTOR_ADDRESS = ["14 Larch Rise", "Halbridge", "West Yorkshire", "HX7 9RT"]

NOMINAL_ACCOUNTS = {
    "5000": "Purchases - materials",
    "5010": "Subcontract costs",
    "6100": "Marketing & advertising",
    "6200": "Professional fees",
    "6300": "Rent & rates",
    "6400": "Light, heat & power",
    "6500": "IT & software",
    "6600": "Travel & subsistence",
    "6700": "Repairs & maintenance",
    "6800": "Administrative expenses",
    "6900": "Insurance",
    "0030": "Plant & machinery",
    "0040": "Office equipment",
}

# The nominal code a correctly-posted invoice of each category goes to.
CATEGORY_CODE = {
    "Cost of sales": "5000",
    "Marketing": "6100",
    "Professional fees": "6200",
    "Premises (rent & rates)": "6300",
    "Utilities": "6400",
    "IT & software": "6500",
    "Travel & subsistence": "6600",
    "Repairs & maintenance": "6700",
    "Administrative expenses": "6800",
    "Insurance": "6900",
    "Fixed assets (capital)": "0030",
}


@dataclass(frozen=True)
class Supplier:
    key: str
    name: str
    vat_number: str
    address: tuple[str, ...]
    email: str
    category: str
    number_format: str  # str.format pattern taking n (and yyyy)
    currency: str = "GBP"
    vat_rate: Decimal = Decimal("20")
    amount_range: tuple[int, int] = (100, 3000)


SUPPLIERS = {
    s.key: s
    for s in [
        Supplier("lumen", "Lumen Print & Design Ltd", "GB284716359", ("27 Gatehouse Street", "Leedham", "LS9 3PW"),
                 "accounts@lumenprintdesign.example", "Marketing", "LPD-{n:05d}", amount_range=(250, 4000)),
        Supplier("carter", "Carter & Vale LLP", "GB517390284", ("Kingsmere House, 8 Bank Row", "Halbridge", "HX1 2BD"),
                 "billing@cartervale.example", "Professional fees", "CV/{yy}/{n:04d}", amount_range=(800, 6000)),
        Supplier("oakridge", "Oakridge Property Management Ltd", "GB630184527", ("Oakridge House", "Wakeby", "WF3 8HN"),
                 "rent@oakridgepm.example", "Premises (rent & rates)", "OPM{n:06d}", amount_range=(4000, 9000)),
        Supplier("greenline", "Greenline Energy Supply Ltd", "GB742905186", ("PO Box 7731", "Bristow", "BS99 4GE"),
                 "billing@greenline-energy.example", "Utilities", "GE-{n:07d}", amount_range=(600, 3500)),
        Supplier("stackwise", "Stackwise Software Ltd", "GB395261840",
                 ("Floor 3, 11 Canal Wharf", "Manchley", "M4 6TS"), "invoices@stackwise.example", "IT & software",
                 "SW-{n:05d}", amount_range=(150, 5000)),
        Supplier("meridian", "Meridian Business Travel Ltd", "GB863047215", ("1 Concourse Way", "Sheffley", "S1 2RF"),
                 "accounts@meridianbt.example", "Travel & subsistence", "MBT{n:05d}", amount_range=(180, 2200)),
        Supplier("fixwell", "Fixwell Facilities Ltd", "GB174582936", ("Unit 9, Brook Park", "Halbridge", "HX5 3LS"),
                 "accounts@fixwell.example", "Repairs & maintenance", "FX-{n:04d}", amount_range=(200, 3000)),
        Supplier("pemberton", "Pemberton Steel Stockholders Ltd", "GB928310475", ("Forge Road", "Rotherby", "S60 1PQ"),
                 "sales.ledger@pembertonsteel.example", "Cost of sales", "PSS{n:05d}", amount_range=(1500, 9500)),
        Supplier("harbour", "Harbour Office Supplies Ltd", "GB451927368", ("45 Quayside Road", "Hullbridge", "HU1 4DX"),
                 "orders@harbouroffice.example", "Administrative expenses", "INV{n:04d}", amount_range=(60, 900)),
        Supplier("kestrel", "Kestrel Insurance Brokers Ltd", "GB206593871", ("6 Exchange Square", "Yorvik", "YO1 7KB"),
                 "premiums@kestrelib.example", "Insurance", "KIB/{n:05d}", vat_rate=Decimal("0"),
                 amount_range=(1200, 8000)),
        Supplier("atlas", "Atlas Machine Tools Ltd", "GB739164250", ("Atlas Works, Mill Lane", "Derwent", "DE21 5TT"),
                 "invoicing@atlasmt.example", "Fixed assets (capital)", "ATL-{n:04d}", amount_range=(6000, 25000)),
        Supplier("bauer", "Bauer Komponenten GmbH", "DE318274695", ("Industriestraße 42", "70565 Stuttgart", "Germany"),
                 "rechnung@bauer-komponenten.example", "Cost of sales", "RE-{yyyy}-{n:04d}", currency="EUR",
                 vat_rate=Decimal("0"), amount_range=(1500, 6000)),
        Supplier("summit", "Summit Cloud Inc.", "US 84-2917365", ("500 Harbor Blvd, Suite 210", "Portland, OR 97204",
                 "USA"), "billing@summitcloud.example", "IT & software", "SC-{n:06d}", currency="USD",
                 vat_rate=Decimal("0"), amount_range=(300, 2500)),
    ]
}  # fmt: skip

# Extra fictional suppliers that only appear as filler lines in the ledgers.
FILLER_SUPPLIERS = [
    ("Ashgrove Fasteners Ltd", "Cost of sales"),
    ("Brightwater Cleaning Services Ltd", "Administrative expenses"),
    ("Corvid Logistics Ltd", "Cost of sales"),
    ("Dunmore Hydraulics Ltd", "Repairs & maintenance"),
    ("Elmstead Packaging Ltd", "Cost of sales"),
    ("Foxley Signs & Graphics Ltd", "Marketing"),
    ("Granby Payroll Bureau Ltd", "Professional fees"),
    ("Hollins Water Services Ltd", "Utilities"),
    ("Ironbridge Welding Supplies Ltd", "Cost of sales"),
    ("Juniper Telecoms Ltd", "IT & software"),
    ("Kinross Couriers Ltd", "Administrative expenses"),
    ("Lowther Safety Equipment Ltd", "Repairs & maintenance"),
    ("Moorcroft Waste Management Ltd", "Utilities"),
    ("Northgate Coffee Supplies Ltd", "Administrative expenses"),
    ("Orchard Lane Hotels Ltd", "Travel & subsistence"),
    ("Pinfold Precision Castings Ltd", "Cost of sales"),
]
