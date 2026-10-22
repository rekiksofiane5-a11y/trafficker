"""Export « Instant reporting » CM360 au format réel (constaté) : classeur non standard
(workbook.xml à la racine, feuille xl/worksheets/data.xml, stylesheet.xml incomplet,
chaînes en ligne), bloc d'en-tête, « Report Fields », « Grand Total: ». openpyxl échoue dessus."""
import sys
import zipfile
from xml.sax.saxutils import escape

ROWS = [  # Date, Site (CM360), Placement, Placement ID, Impressions, Clicks, Click Rate
    ("2026-10-01", "AMNET", "R-CONVERSION-CPM-AMNET--SOCIODEMO-NA-COLLECTIONAD-1x1-Multidevice-NA", "456219030", 0, 28, 0.0),
    ("2026-10-01", "The Trade Desk", "R-NOTORIETE-CPM-LEMONDE--CUSTOM-LeMonde-GRANDANGLE-1x1-Multidevice-NA", "451000001", 91000, 150, 0.16),
    ("2026-10-02", "The Trade Desk", "R-NOTORIETE-CPM-LEMONDE--CUSTOM-LeMonde-GRANDANGLE-1x1-Multidevice-NA", "451000001", 88000, 140, 0.16),
    ("2026-10-02", "Teads FR", "R-NOTORIETE-CPM-TEADSADMANAGER-GRANDPUBLIC-CUSTOM-Data3565-INSTREAM-1x1-Multidevice-NA", "452000002", 50000, 20, 0.04),
]


def _cell(ref, value, style=6):
    if isinstance(value, (int, float)):
        return f'<c r="{ref}" s="{style + 1}" t="n"><v>{value}</v></c>'
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'


HEADER = ["Date", "Site (CM360)", "Placement", "Placement ID", "Impressions", "Clicks", "Click Rate"]


def build(path, header=None, data=None, date_range="01/10/2026 - 02/10/2026", generated="02/10/2026 17:33"):
    header, data = header or HEADER, data or ROWS
    head = [("Date/Time Generated", generated), ("Report Time Zone", "Europe/Paris"), ("Account ID", "3021"),
            ("Date Range", date_range), ("Reporting numbers are finalized after seven days.", "")]
    n_dims = sum(1 for h in header if h not in ("Impressions", "Clicks", "Click Rate"))
    rows = [[k, v] for k, v in head] + [[], [], ["Report Fields"] + [""] * (n_dims - 1) + ["Report Metrics"], list(header)]
    rows += [list(r) for r in data]
    imp, clk = header.index("Impressions"), header.index("Clicks")
    ti, tc = sum(r[imp] for r in data), sum(r[clk] for r in data)
    rows.append(["Grand Total:"] + ["---"] * (n_dims - 1) + [ti, tc, round(tc / ti * 100, 2) if ti else 0])
    xml_rows = []
    for i, r in enumerate(rows, start=1):
        cells = "".join(_cell(f"{chr(65 + j)}{i}", v) for j, v in enumerate(r) if v != "" or j == 0)
        xml_rows.append(f'<row r="{i}">{cells}</row>')
    sheet = ('<?xml version="1.0" encoding="utf-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/'
             'spreadsheetml/2006/main"><sheetData>' + "".join(xml_rows) + '</sheetData><mergeCells count="1">'
             '<mergeCell ref="A9:D9"/></mergeCells></worksheet>')
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("_rels/.rels", f'<?xml version="1.0"?><Relationships xmlns="{pkg}"><Relationship Type="{rel}/officeDocument" '
                                  'Target="workbook.xml" Id="rw_1"/></Relationships>')
        z.writestr("_rels/workbook.xml.rels", f'<?xml version="1.0"?><Relationships xmlns="{pkg}"><Relationship Type="{rel}/worksheet" '
                                              f'Target="/xl/worksheets/data.xml" Id="r_1"/><Relationship Type="{rel}/styles" '
                                              'Target="stylesheet.xml" Id="r_2"/></Relationships>')
        z.writestr("workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                                   f'xmlns:r="{rel}"><sheets><sheet name="Data" sheetId="1" r:id="r_1"/></sheets></workbook>')
        z.writestr("xl/worksheets/data.xml", sheet)
        z.writestr("stylesheet.xml", '<?xml version="1.0"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                                     '<cellXfs count="1"><xf/></cellXfs></styleSheet>')
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                                          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                                          '<Override PartName="/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.'
                                          'spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/data.xml" ContentType='
                                          '"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')


if __name__ == "__main__":
    build(sys.argv[1])
