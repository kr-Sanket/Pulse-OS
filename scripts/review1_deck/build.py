"""PulseOS Review-1 deck — visual redesign (icon cards, flows, timeline, chart)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import *
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION

prs = Presentation()
prs.slide_width = SW; prs.slide_height = SH

# ---------- extra visual helpers ----------
def icon_circle(s, cx, cy, d, emoji, fill=BLUE_LT, esize=20):
    c = s.shapes.add_shape(MSO_SHAPE.OVAL, cx, cy, d, d)
    set_fill(c, fill); c.shadow.inherit = False
    tf = c.text_frame; tf.word_wrap = False
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = emoji; r.font.size = Pt(esize)
    return c

def icard(s, x, y, w, h, emoji, title, sub, fill=GRAY_LT, tsize=13.5, ssize=11,
          esize=19, tcolor=NAVY):
    """icon card: emoji circle top-left, bold title, one-line sub."""
    box(s, x, y, w, h, fill=fill, radius=0.09, text=None)
    d = Inches(0.62)
    icon_circle(s, x + Inches(0.18), y + Inches(0.16), d, emoji, fill=WHITE, esize=esize)
    textbox(s, x + Inches(0.95), y + Inches(0.17), w - Inches(1.1), Inches(0.6), title,
            size=tsize, color=tcolor, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    textbox(s, x + Inches(0.2), y + Inches(0.92), w - Inches(0.4), h - Inches(1.0), sub,
            size=ssize, color=GRAY, line=1.05)

def vcard(s, x, y, w, h, emoji, title, sub, fill=GRAY_LT, tsize=13, ssize=10.5, esize=22):
    """vertical card: centered emoji circle, title, sub."""
    box(s, x, y, w, h, fill=fill, radius=0.10, text=None)
    d = Inches(0.72)
    icon_circle(s, x + (w - d) // 2, y + Inches(0.18), d, emoji, fill=WHITE, esize=esize)
    textbox(s, x + Inches(0.08), y + Inches(1.0), w - Inches(0.16), Inches(0.45), title,
            size=tsize, color=NAVY, bold=True, align=PP_ALIGN.CENTER)
    textbox(s, x + Inches(0.12), y + Inches(1.42), w - Inches(0.24), h - Inches(1.5), sub,
            size=ssize, color=GRAY, align=PP_ALIGN.CENTER, line=1.05)

def banner(s, y, text_runs, fill=NAVY, h=Inches(0.7)):
    box(s, MARGIN, y, Inches(12.23), h, fill=fill, radius=0.09,
        text=[text_runs], align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE, ln=1.1)

W_INK = RGBColor(0xDC, 0xE6, 0xF1)

# ============================================================ 1 · TITLE
s = new_slide(prs)
band = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SW, Inches(0.14))
set_fill(band, TEAL)
textbox(s, Inches(0.9), Inches(0.5), Inches(11.5), Inches(0.35),
        "B.Tech — Computer Science and Engineering   ·   BCSE497J — Project I   ·   Review 1",
        size=14, color=GRAY_MED, align=PP_ALIGN.CENTER)
textbox(s, Inches(0.9), Inches(1.25), Inches(11.5), Inches(0.9), "PulseOS",
        size=54, color=NAVY, bold=True, align=PP_ALIGN.CENTER, font="Calibri Light")
textbox(s, Inches(1.2), Inches(2.25), Inches(10.9), Inches(0.85),
        "AI-Driven Healthcare Interoperability Platform using HL7 FHIR, Retrieval-Augmented "
        "Generation (RAG), Blockchain Audit Logging and Consent Management",
        size=17, color=TEAL, align=PP_ALIGN.CENTER, line=1.15)
for i, (em, t) in enumerate([("📋", "HL7 FHIR"), ("🤖", "RAG AI"), ("🔑", "Consent"), ("⛓", "Blockchain")]):
    x = Inches(3.05) + i * Inches(1.9)
    box(s, x, Inches(3.3), Inches(1.7), Inches(0.42), fill=GRAY_LT, radius=0.5,
        text=[[(em + "  ", {"size": 12}), (t, {"size": 11.5, "bold": True, "color": NAVY})]])
textbox(s, Inches(0.9), Inches(4.0), Inches(11.5), Inches(0.35), "Team Members",
        size=13, color=GRAY_MED, bold=True, align=PP_ALIGN.CENTER)
members = [("Sanket Kumar", "23BDS0106"), ("Divyanshu Kumar", "23BDS0107"),
           ("Abhishek Kritin S R", "23BCE2034")]
mw, mx = Inches(3.2), Inches(1.62)
for i, (nm, reg) in enumerate(members):
    x = mx + i * (mw + Inches(0.25))
    box(s, x, Inches(4.45), mw, Inches(0.85), fill=BLUE_LT,
        text=[[(nm, {"bold": True, "size": 15, "color": NAVY})],
              [(reg, {"size": 12.5, "color": GRAY_MED})]], space_after=1)
textbox(s, Inches(0.9), Inches(5.6), Inches(11.5), Inches(0.35),
        [[("Faculty Guide:  ", {"bold": True, "color": GRAY_MED}),
          ("«Guide Name», SCOPE, VIT", {"color": GRAY})]],
        size=14, align=PP_ALIGN.CENTER)
textbox(s, Inches(0.9), Inches(6.35), Inches(11.5), Inches(0.35),
        "School of Computer Science and Engineering (SCOPE)   ·   " + DATE,
        size=12, color=GRAY_MED, align=PP_ALIGN.CENTER)
notes(s, "• Introduce the team and the title.\n"
         "• One line: a patient's complete medical history in one place, with AI help "
         "and patient-controlled access.\n"
         "• Review 1 = problem, literature, gap, plan.")

# ============================================================ 2 · AIM
s = new_slide(prs, "Aim")
textbox(s, Inches(1.3), Inches(1.9), Inches(10.7), Inches(1.9),
        [[("One platform where a patient's complete medical history is ", {}),
          ("standardized", {"bold": True, "color": TEAL}),
          (" (HL7 FHIR), ", {}),
          ("understood by AI", {"bold": True, "color": TEAL}),
          (" (RAG), ", {}),
          ("shared only with consent", {"bold": True, "color": TEAL}),
          (", and ", {}),
          ("verifiable on a blockchain", {"bold": True, "color": TEAL}),
          (".", {})]],
        size=24, color=GRAY, align=PP_ALIGN.CENTER, line=1.35, font="Calibri Light")
cards = [("🔗", "Interoperable", "One standard — FHIR"),
         ("🤖", "Intelligent", "AI grounded in records"),
         ("🔑", "Patient-Owned", "Category-wise consent"),
         ("⛓", "Trustworthy", "Every access auditable")]
for i, (em, t, d) in enumerate(cards):
    vcard(s, Inches(0.85) + i * Inches(3.0), Inches(4.15), Inches(2.75), Inches(2.15),
          em, t, d, fill=BLUE_LT if i % 2 == 0 else TEAL_LT)
notes(s, "• Read the aim once, slowly.\n"
         "• The four cards are the four pillars — every later slide belongs to one.\n"
         "• Transition: the whole story in five steps.")

# ============================================================ 3 · ABSTRACT
s = new_slide(prs, "Abstract", "The project in five steps")
tiles = [("😕", "Problem", "Records scattered across\nhospitals & formats"),
         ("💡", "Idea", "One FHIR health history\nper patient"),
         ("🤖", "AI", "RAG answers from the\npatient's own records"),
         ("🔑", "Trust", "Consent + blockchain\naudit on every access"),
         ("🧪", "Dataset", "1,180 synthetic Synthea\npatients — no real data")]
x = Inches(0.62)
for i, (em, t, d) in enumerate(tiles):
    vcard(s, x, Inches(2.25), Inches(2.15), Inches(2.75), em, t, d,
          fill=GRAY_LT if i == 0 else (TEAL_LT if i in (2, 3) else BLUE_LT))
    if i < 4:
        arrow_r(s, x + Inches(2.19), Inches(3.5), w=Inches(0.26), h=Inches(0.24))
    x += Inches(2.48)
banner(s, Inches(5.55),
       [("In short:  ", {"bold": True, "color": WHITE, "size": 13.5}),
        ("we standardize the data, ground the AI in it, and put the patient in charge "
         "of who sees what.", {"color": W_INK, "size": 13})])
notes(s, "• Walk left to right: problem → idea → AI → trust → dataset.\n"
         "• Stress: no model training, no real patient data.\n"
         "• Transition: the problem in detail.")

# ============================================================ 4 · PROBLEM
s = new_slide(prs, "Problem Statement", "Six reasons sharing medical data fails today")
probs = [("📂", "Scattered records", "Every hospital keeps its own copy"),
         ("🔀", "No common format", "EMR systems can't exchange records"),
         ("🔁", "Repeated tests", "Old reports missing → tests redone"),
         ("✍️", "Weak consent", "One signature — no control, no revoking"),
         ("🚫", "No ownership", "Patients can't manage their own history"),
         ("❓", "AI without trust", "Health AI shows answers, not sources")]
for i, (em, t, d) in enumerate(probs):
    x = MARGIN + (i % 3) * Inches(4.12)
    y = Inches(1.85) + (i // 3) * Inches(1.85)
    icard(s, x, y, Inches(3.92), Inches(1.62), em, t, d)
banner(s, Inches(5.85),
       [("The cost:  ", {"bold": True, "color": WHITE, "size": 13.5}),
        ("repeated tests, delayed diagnosis, avoidable mistakes — a patient-safety "
         "problem, not just an IT problem.", {"color": W_INK, "size": 13})])
notes(s, "• Top row: data problems. Bottom row: control and trust problems.\n"
         "• One relatable example: a family moves cities, years of reports are lost.\n"
         "• Key line: patient safety, not just IT.\n"
         "• Transition: what do existing systems do?")

# ============================================================ 5 · EXISTING SOLUTIONS
s = new_slide(prs, "Existing Solutions", "Good at their job — but built for institutions")
rows = [["", "System", "Type", "Strength", "Gap for our goals"],
        ["🌍", "OpenMRS", "Open-source EMR", "Free, flexible, big community",
         "Single hospital; no patient consent"],
        ["🏥", "OpenEMR", "Open-source clinic EMR", "Full clinic workflow",
         "No cross-hospital sharing; no AI"],
        ["💼", "Epic", "Commercial EHR", "Mature; FHIR APIs; exchange network",
         "Costly; vendor lock-in"],
        ["🏢", "Oracle Cerner", "Commercial EHR", "Large deployments",
         "Lock-in; patient control secondary"],
        ["🇮🇳", "ABDM", "National health mission", "ABHA ID; consent framework; FHIR",
         "Rolling out; no AI; ordinary audit logs"]]
tbl = make_table(s, MARGIN, Inches(1.85), Inches(12.23), Inches(3.6), rows,
                 [0.55, 1.5, 2.2, 3.3, 3.4], size=12, header_size=12,
                 aligns=[PP_ALIGN.CENTER] + [PP_ALIGN.LEFT] * 4, first_col_bold=False)
for ri in range(1, 6):
    tbl.cell(ri, 0).text_frame.paragraphs[0].runs[0].font.size = Pt(16)
    for r in tbl.cell(ri, 1).text_frame.paragraphs[0].runs:
        r.font.bold = True; r.font.color.rgb = NAVY
banner(s, Inches(5.85),
       [("PulseOS is different:  ", {"bold": True, "color": WHITE, "size": 13.5}),
        ("built around the patient — FHIR + consent + verifiable audit + grounded AI "
         "in one platform.", {"color": W_INK, "size": 13})], fill=TEAL)
notes(s, "• We are not criticising these systems — each is good at its job.\n"
         "• ABDM is closest to our idea — but no AI, and normal database audit logs.\n"
         "• Our difference: everything together, with the patient in charge.\n"
         "• Transition: what researchers have already tried.")

# ============================================================ 6 · LITERATURE REVIEW
s = new_slide(prs, "Literature Review", "Six key papers — one line each")
rows = [["Paper", "Focus", "Key idea", "Limitation", "What we take"],
        ["FHIR-RAG-MEDS [1]\n2026", "🤖 AI + FHIR",
         "RAG over live FHIR records beats dedicated medical LLMs",
         "Small synthetic test set", "Our RAG design"],
        ["LLM ↔ FHIR [2]\n2023", "🤖 AI + FHIR",
         "GPT-4 converts clinical text to valid FHIR (>90% accuracy)",
         "One resource type only", "LLMs handle FHIR well"],
        ["WiraChain [3]\n2026", "⛓ Platform",
         "Working FHIR + blockchain platform; patients grant/revoke access",
         "Simulation only; no AI", "The platform pattern"],
        ["Blockchain review [4]\n2026", "⛓ Survey",
         "32 studies: records off-chain, only hashes on-chain",
         "Few real deployments", "Hash-only audit rule"],
        ["FHIR Consent [5]\n2026", "🔑 Consent",
         "Split consent: how it's stored / enforced / verified",
         "Concept only", "Our consent design"],
        ["Revocable consent [6]\n2026", "🔑 Survey",
         "55 systems claim revocation — only 5 show it reaching the database",
         "None measure it", "Our evaluation goal"]]
tbl = make_table(s, MARGIN, Inches(1.8), Inches(12.23), Inches(4.4), rows,
                 [2.0, 1.5, 4.3, 2.2, 2.2], size=11, header_size=12)
textbox(s, MARGIN, Inches(6.55), Inches(12.2), Inches(0.35),
        "Supporting papers [7]–[11]: medical RAG summarization, Polygon health records, "
        "consent prototype, identity & IoT security surveys.",
        size=10.5, color=GRAY_MED)
notes(s, "• Two AI papers, two blockchain papers, two consent papers.\n"
         "• Paper 1 proves our AI pattern; paper 3 is the closest full system — no AI.\n"
         "• Paper 6 is the gap: revocation claimed everywhere, shown almost nowhere.\n"
         "• Transition: side by side, the gap becomes visible.")

# ============================================================ 7 · RESEARCH GAP
s = new_slide(prs, "Research Gap", "Everyone solves one piece — nobody combines them")
CAPS = ["FHIR", "LLM / RAG", "Blockchain", "Dynamic\nConsent", "Patient\nControl",
        "Verifiable\nAudit", "Unified\nPlatform"]
def marks(*m): return list(m)
gap_rows = [["Work"] + CAPS,
    ["FHIR-RAG-MEDS [1]"]     + marks("✓","✓","✗","✗","✗","✗","✗"),
    ["LLM ↔ FHIR [2]"]        + marks("✓","✓","✗","✗","✗","✗","✗"),
    ["WiraChain [3]"]         + marks("✓","✗","✓","✓","✓","✓","✗"),
    ["Blockchain review [4]"] + marks("~","✗","✓","~","~","✓","✗"),
    ["FHIR Consent [5]"]      + marks("✓","✗","~","✓","~","✓","✗"),
    ["Revocable consent [6]"] + marks("~","✗","✓","✓","✓","✓","✗"),
    ["PulseOS (proposed)"]    + marks("✓","✓","✓","✓","✓","✓","✓"),
]
t = make_table(s, MARGIN, Inches(1.80), Inches(12.23), Inches(3.7), gap_rows,
               [2.6] + [1.37]*7, size=13, header_size=10.5,
               aligns=[PP_ALIGN.LEFT] + [PP_ALIGN.CENTER]*7)
for ri in range(1, 8):
    for ci in range(1, 8):
        run = t.cell(ri, ci).text_frame.paragraphs[0].runs[0]
        run.font.color.rgb = GREEN if run.text == "✓" else (ORANGE if run.text == "~" else
                                                            RGBColor(0xC9, 0xC9, 0xC9))
        run.font.size = Pt(14); run.font.bold = True
    if ri == 7:
        for ci in range(8):
            c = t.cell(ri, ci); c.fill.solid(); c.fill.fore_color.rgb = TEAL_LT
            for p in c.text_frame.paragraphs:
                for r in p.runs: r.font.bold = True
textbox(s, MARGIN, Inches(5.6), Inches(12.2), Inches(0.28),
        [[("✓", {"color": GREEN, "bold": True}), ("  covered     ", {"color": GRAY_MED}),
          ("~", {"color": ORANGE, "bold": True}), ("  partly     ", {"color": GRAY_MED}),
          ("✗", {"color": RGBColor(0xC9,0xC9,0xC9), "bold": True}), ("  not covered", {"color": GRAY_MED})]],
        size=11)
banner(s, Inches(5.95),
       [("The gap:  ", {"bold": True, "color": WHITE, "size": 13.5}),
        ("no single patient-centric platform combines FHIR + RAG + consent + verifiable "
         "audit. PulseOS fills that last column.", {"color": W_INK, "size": 13})],
       fill=ORANGE)
notes(s, "• Spend a full minute here — this slide justifies the project.\n"
         "• Read the last column: 'Unified Platform' is empty for everyone.\n"
         "• What is new from us: the combination, plus showing revocation actually work.\n"
         "• Transition: the gap becomes our objectives.")

# ============================================================ 8 · OBJECTIVES
s = new_slide(prs, "Objectives", "Five goals — data, AI, control, audit, delivery")
objs = [("🧱", "O1 · Data pipeline", "Parse & load 1,180\nFHIR bundles"),
        ("🤖", "O2 · AI assistance", "RAG summaries\nand Q&A"),
        ("🔑", "O3 · Patient control", "Category-wise,\nrevocable consent"),
        ("⛓", "O4 · Verifiable audit", "Every access\nhashed on-chain"),
        ("🖥", "O5 · Deliver & test", "Portals + end-to-end\nevaluation")]
for i, (em, t, d) in enumerate(objs):
    vcard(s, Inches(0.55) + i * Inches(2.48), Inches(1.85), Inches(2.32), Inches(2.5),
          em, t, d, fill=BLUE_LT if i % 2 == 0 else TEAL_LT, tsize=12.5)
box(s, MARGIN, Inches(4.75), Inches(6.0), Inches(1.85), fill=GRAY_LT, radius=0.09,
    text=[[("🎯  Sustainable Development Goals", {"bold": True, "size": 13, "color": NAVY})],
          [("SDG 3 — Good Health & Well-Being", {"size": 12, "color": GRAY})],
          [("SDG 9 — Industry, Innovation & Infrastructure", {"size": 12, "color": GRAY})]],
    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE, space_after=6)
box(s, Inches(6.78), Inches(4.75), Inches(6.0), Inches(1.85), fill=TEAL_LT, radius=0.09,
    text=[[("🏁  Expected Outcomes", {"bold": True, "size": 13, "color": NAVY})],
          [("Working PulseOS prototype on Synthea data", {"size": 12, "color": GRAY})],
          [("Research paper → Scopus-indexed conference", {"size": 12, "color": GRAY})]],
    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE, space_after=6)
notes(s, "• Five objectives, each mapping to a problem from slide 4.\n"
         "• O5 makes it a product, not just a pipeline.\n"
         "• Outcomes: prototype + paper submission.\n"
         "• Transition: the system that delivers them.")

# ============================================================ 9 · PROPOSED SOLUTION
s = new_slide(prs, "Proposed Solution — PulseOS", "Four pillars around one idea")
hub = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(5.17), Inches(3.15), Inches(3.0), Inches(2.0))
set_fill(hub, NAVY); hub.shadow.inherit = False
tf = hub.text_frame; tf.word_wrap = True; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
_p = tf.paragraphs[0]; _p.alignment = PP_ALIGN.CENTER
r = _p.add_run(); r.text = "PulseOS"; r.font.size = Pt(20); r.font.bold = True
r.font.color.rgb = WHITE
p2 = tf.add_paragraph(); p2.alignment = PP_ALIGN.CENTER
r2 = p2.add_run(); r2.text = "the patient at\nthe center"
r2.font.size = Pt(11.5); r2.font.color.rgb = W_INK
corners = [
    (Inches(0.7), Inches(1.7), "📋", "Interoperable core",
     "All records as HL7 FHIR — JSON + tables", "based on [1][2][3]", BLUE_LT),
    (Inches(8.05), Inches(1.7), "🤖", "Grounded intelligence",
     "RAG over records + knowledge, with sources", "based on [1][7]", TEAL_LT),
    (Inches(0.7), Inches(4.85), "🔑", "Patient-governed consent",
     "Category-wise · time-limited · revocable", "based on [5][6]", TEAL_LT),
    (Inches(8.05), Inches(4.85), "⛓", "Verifiable audit",
     "Every event hashed onto a public chain", "based on [3][4]", BLUE_LT),
]
for cx, cy, em, t, d, src, f in corners:
    ln = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,
                                cx + Inches(2.3), cy + Inches(0.8),
                                Inches(6.67), Inches(4.15))
    ln.line.color.rgb = BORDER; ln.line.width = Pt(1.5)
for cx, cy, em, t, d, src, f in corners:
    box(s, cx, cy, Inches(4.6), Inches(1.6), fill=f, radius=0.10, text=None)
    icon_circle(s, cx + Inches(0.18), cy + Inches(0.16), Inches(0.62), em, fill=WHITE)
    textbox(s, cx + Inches(0.95), cy + Inches(0.14), Inches(3.5), Inches(0.4), t,
            size=13.5, color=NAVY, bold=True)
    textbox(s, cx + Inches(0.95), cy + Inches(0.56), Inches(3.55), Inches(0.6), d,
            size=11, color=GRAY, line=1.05)
    textbox(s, cx + Inches(0.95), cy + Inches(1.18), Inches(3.5), Inches(0.3), src,
            size=9.5, color=TEAL, bold=True)
# re-add hub on top of connectors
s.shapes._spTree.remove(hub._element); s.shapes._spTree.append(hub._element)
notes(s, "• One idea in the middle: the patient is the point of integration.\n"
         "• Each pillar card names the papers it builds on — the pieces exist.\n"
         "• What is new: the combination, and consent applying to the AI too.\n"
         "• Transition: how the pillars connect — the architecture.")

# ============================================================ 10 · ARCHITECTURE
s = new_slide(prs, "System Architecture", "Six layers — data flows up, every request passes the consent layer")
LX, LW = Inches(0.55), Inches(9.35)
layers = [
    ("🖥  FRONTEND", "Patient · Doctor · Hospital portals (React / Next.js)", BLUE_LT),
    ("🔑  TRUST", "Consent check → audit log → blockchain anchor", AMBER_LT),
    ("🤖  AI", "RAG engine (LangChain) · LLM · knowledge base", TEAL_LT),
    ("🗄  STORAGE", "PostgreSQL — FHIR JSON · tables · vectors (pgvector)", BLUE_LT),
    ("⚙️  INGESTION", "Parse → validate → transform → load", TEAL_LT),
    ("🧪  DATA", "Synthea — 1,180 FHIR patient bundles", GRAY_LT),
]
y = Inches(1.8)
for i, (name, desc, f) in enumerate(layers):
    box(s, LX, y, Inches(2.35), Inches(0.66), fill=NAVY, radius=0.10,
        text=name, size=12, color=WHITE, bold=True, align=PP_ALIGN.LEFT)
    box(s, LX + Inches(2.5), y, LW - Inches(2.5), Inches(0.66), fill=f, radius=0.08,
        text=desc, size=13, color=GRAY, align=PP_ALIGN.LEFT)
    if i < len(layers) - 1:
        arrow_d(s, LX + LW // 2, y + Inches(0.68), w=Inches(0.20), h=Inches(0.14),
                color=GRAY_MED)
    y += Inches(0.82)
box(s, Inches(10.2), Inches(1.8), Inches(2.58), Inches(4.7), fill=AMBER_LT, radius=0.09,
    text=[[("🔒", {"size": 22})],
          [("No bypass", {"bold": True, "size": 14, "color": ORANGE})],
          [("Every request — from a person or from the AI — is consent-checked, "
            "logged, and anchored.", {"size": 11.5, "color": GRAY})]],
    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, space_after=8, ln=1.15)
notes(s, "• Walk bottom-up: dataset → ingestion → storage → AI → trust → frontend.\n"
         "• Storage is one PostgreSQL: JSON, tables, vectors.\n"
         "• The trust layer sits between AI and frontend — nothing goes around it.\n"
         "• Transition: the dataset everything rests on.")

# ============================================================ 11 · DATASET
s = new_slide(prs, "Dataset — Synthea Synthetic EHR", "Realistic FHIR patients, zero privacy risk")
stats = [("🧑‍⚕️", "1,180", "synthetic patients"),
         ("📦", "5.2 lakh+", "FHIR resources"),
         ("🧩", "15+", "resource types"),
         ("🔒", "100%", "synthetic — no real data")]
for i, (em, v, l) in enumerate(stats):
    x = MARGIN + i * Inches(3.12)
    box(s, x, Inches(1.8), Inches(2.9), Inches(1.05), fill=NAVY, radius=0.10,
        text=[[(em + "  ", {"size": 14}), (v, {"bold": True, "size": 21, "color": WHITE})],
              [(l, {"size": 10.5, "color": RGBColor(0xC9, 0xD8, 0xE8)})]], space_after=1)
# --- bar chart: resource distribution (single series, teal, no legend) ---
cd = CategoryChartData()
res = [("Observation", 259929), ("Claim", 60970), ("Encounter", 46868),
       ("Expl. of Benefit", 46868), ("Procedure", 36451), ("DiagnosticReport", 18304),
       ("Immunization", 15013), ("MedicationRequest", 14102), ("Condition", 8766)]
cd.categories = [n for n, _ in reversed(res)]
cd.add_series("Resources", [v for _, v in reversed(res)])
gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(0.55), Inches(3.15),
                        Inches(7.6), Inches(3.7), cd)
ch = gf.chart
ch.has_legend = False; ch.has_title = False
plot = ch.plots[0]; plot.gap_width = 55
ser = plot.series[0]
ser.format.fill.solid(); ser.format.fill.fore_color.rgb = TEAL
ser.format.line.fill.background()
dl = ser.data_labels
dl.show_value = True; dl.number_format = '#,##0'; dl.number_format_is_linked = False
dl.position = XL_LABEL_POSITION.OUTSIDE_END
dl.font.size = Pt(9); dl.font.color.rgb = GRAY
va = ch.value_axis
va.visible = False; va.has_major_gridlines = False
ca = ch.category_axis
ca.tick_labels.font.size = Pt(10); ca.tick_labels.font.color.rgb = GRAY
ca.format.line.color.rgb = BORDER
bullets(s, Inches(8.55), Inches(3.35), Inches(4.25), Inches(3.3), [
    ("Open & free — ", "standard research dataset"),
    ("Native FHIR R4 — ", "same format real hospitals use"),
    ("Lifelong histories — ", "ideal for summaries & timelines"),
    ("Privacy-safe — ", "demo and publish freely"),
], size=12, gap=10, line=1.05)
notes(s, "• Numbers measured from our own copy of the dataset.\n"
         "• One JSON file = one patient's entire medical life.\n"
         "• Observations dominate — rich material for the AI to summarize.\n"
         "• Synthetic data = no ethics or privacy risk.\n"
         "• Transition: how raw bundles become usable data.")

# ============================================================ 12 · PIPELINE
s = new_slide(prs, "Data Processing Pipeline", "From raw bundles to AI-ready data")
steps = ["FHIR\nBundle", "Parser", "Validation", "Transform", "PostgreSQL",
         "Embeddings", "Vector\nindex", "AI"]
subs = ["1,180 JSON\nfiles", "read &\nresolve links", "check structure\n& codes",
        "FHIR → table\nrows", "JSON + tables", "text →\nvectors", "pgvector",
        "RAG"]
hflow(s, Inches(0.45), Inches(2.5), steps, Inches(1.28), Inches(0.85),
      gap=Inches(0.27), size=11, sub=subs,
      fills=[GRAY_LT, BLUE_LT, BLUE_LT, BLUE_LT, TEAL_LT, TEAL_LT, TEAL_LT, NAVY],
      tcolors=[GRAY, NAVY, NAVY, NAVY, NAVY, NAVY, NAVY, WHITE])
store = [("🗄", "Original JSON", "Full bundle kept as-is — nothing lost"),
         ("📊", "Normalized tables", "Fast queries for portals & timelines"),
         ("🧭", "Vector index", "Meaning-based search — consent filter inside the query")]
for i, (em, t, d) in enumerate(store):
    icard(s, MARGIN + i * Inches(4.14), Inches(4.5), Inches(3.95), Inches(1.5),
          em, t, d, fill=BLUE_LT if i < 1 else (TEAL_LT if i == 1 else AMBER_LT))
textbox(s, MARGIN, Inches(6.3), Inches(12.2), Inches(0.45),
        [[("One database, three views:  ", {"bold": True, "color": NAVY, "size": 12.5}),
          ("detail (JSON), speed (tables), meaning (vectors).", {"color": GRAY, "size": 12.5})]],
        align=PP_ALIGN.CENTER)
notes(s, "• Walk the flow once, left to right.\n"
         "• Validation matters — bad data would break everything after it.\n"
         "• Same data stored three ways, one PostgreSQL.\n"
         "• Transition: the AI on top.")

# ============================================================ 13 · AI DESIGN
s = new_slide(prs, "AI Design — Retrieval-Augmented Generation",
              "We don't train a model — we ground an existing one")
y0 = Inches(2.0)
box(s, Inches(0.55), y0 + Inches(0.75), Inches(2.15), Inches(0.95), fill=GRAY_LT,
    text="🙋  Question", size=13, color=NAVY, bold=True)
arrow_r(s, Inches(2.78), y0 + Inches(1.11), w=Inches(0.35))
box(s, Inches(3.2), y0, Inches(3.3), Inches(1.05), fill=BLUE_LT,
    text=[[("📄  Patient records", {"bold": True, "size": 13, "color": NAVY})],
          [("own FHIR data — consent applied", {"size": 10.5, "color": GRAY})]], space_after=1)
box(s, Inches(3.2), y0 + Inches(1.25), Inches(3.3), Inches(1.05), fill=BLUE_LT,
    text=[[("📚  Medical knowledge", {"bold": True, "size": 13, "color": NAVY})],
          [("diseases · medicines · labs · procedures", {"size": 10.5, "color": GRAY})]], space_after=1)
arrow_r(s, Inches(6.6), y0 + Inches(1.11), w=Inches(0.35))
box(s, Inches(7.05), y0 + Inches(0.55), Inches(2.2), Inches(1.35), fill=NAVY,
    text=[[("🤖  LLM", {"bold": True, "size": 15, "color": WHITE})],
          [("answers only from retrieved context", {"size": 10.5, "color": W_INK})]], space_after=1)
arrow_r(s, Inches(9.33), y0 + Inches(1.11), w=Inches(0.35))
box(s, Inches(9.78), y0 + Inches(0.55), Inches(3.0), Inches(1.35), fill=TEAL_LT,
    text=[[("✅  Grounded answer", {"bold": True, "size": 13, "color": NAVY})],
          [("with references to source records", {"size": 10.5, "color": GRAY})]], space_after=1)
# example strip
ex = [("Record", "HbA1c = 8.2%", BLUE_LT), ("Knowledge", "above 6.5% = not controlled", TEAL_LT),
      ("AI answer", "“Your diabetes needs attention — ask your doctor.”", AMBER_LT)]
x = Inches(1.15)
textbox(s, MARGIN, Inches(4.75), Inches(12.2), Inches(0.35), "Example — facts + meaning:",
        size=12.5, color=NAVY, bold=True)
for i, (t, d, f) in enumerate(ex):
    wbox = Inches(3.4) if i < 2 else Inches(3.9)
    box(s, x, Inches(5.15), wbox, Inches(0.75), fill=f, radius=0.10,
        text=[[(t + ":  ", {"bold": True, "size": 11.5, "color": NAVY}),
               (d, {"size": 11.5, "color": GRAY})]])
    x += wbox + Inches(0.12)
    if i < 2:
        arrow_r(s, x - Inches(0.06), Inches(5.44), w=Inches(0.22), h=Inches(0.18)); x += Inches(0.22)
textbox(s, MARGIN, Inches(6.25), Inches(12.2), Inches(0.4),
        [[("Why RAG?  ", {"bold": True, "color": NAVY, "size": 12.5}),
          ("answers show sources · new records usable instantly · no training cost [1]",
           {"color": GRAY, "size": 12.5})]], align=PP_ALIGN.CENTER)
notes(s, "• Key message: we ground an existing LLM, we don't train one.\n"
         "• Two sources: the patient's records + general medical knowledge.\n"
         "• Walk the HbA1c example: facts from records, meaning from knowledge.\n"
         "• Transition: the AI only sees what consent allows.")

# ============================================================ 14 · CONSENT
s = new_slide(prs, "Consent Management", "Granular · time-limited · revocable")
csteps = [("🩺", "Doctor requests", "only the categories needed"),
          ("📲", "Patient decides", "approve / reject / revoke per category"),
          ("⏳", "Access is limited", "expires in 90 days by default"),
          ("📜", "Everything logged", "every event → audit trail")]
for i, (em, t, d) in enumerate(csteps):
    x = MARGIN + i * Inches(3.12)
    vcard(s, x, Inches(1.95), Inches(2.9), Inches(2.5), em, f"{i+1} · {t}", d,
          fill=BLUE_LT if i % 2 == 0 else TEAL_LT, tsize=13)
    if i < 3:
        arrow_r(s, x + Inches(2.93), Inches(3.1), w=Inches(0.17), h=Inches(0.24))
banner(s, Inches(4.85),
       [("One rule:  ", {"bold": True, "color": WHITE, "size": 13}),
        ("the consent check runs inside every data request — for doctors and for the AI "
         "alike.", {"color": W_INK, "size": 13})], fill=TEAL)
banner(s, Inches(5.8),
       [("Research angle:  ", {"bold": True, "color": WHITE, "size": 13}),
        ("few published systems show revocation actually working [6] — we will "
         "demonstrate and measure it.", {"color": W_INK, "size": 13})], fill=ORANGE)
notes(s, "• Four steps: request → decide → limited access → logged forever.\n"
         "• Granular: share lab reports without sharing everything.\n"
         "• The same check limits what the AI can read.\n"
         "• Transition: the log itself must be tamper-proof.")

# ============================================================ 15 · BLOCKCHAIN
s = new_slide(prs, "Blockchain — Audit Only, Not Storage",
              "Records stay in PostgreSQL; the chain keeps fingerprints")
box(s, MARGIN, Inches(1.85), Inches(5.8), Inches(2.15), fill=TEAL_LT, radius=0.09,
    text=[[("✓  Goes on the blockchain", {"bold": True, "size": 14, "color": TEAL})],
          [("• Hash (fingerprint) of each audit event", {"size": 12.5, "color": GRAY})],
          [("• Event type — consent given / revoked / accessed", {"size": 12.5, "color": GRAY})],
          [("• Timestamp", {"size": 12.5, "color": GRAY})]],
    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE, space_after=5)
box(s, MARGIN, Inches(4.2), Inches(5.8), Inches(2.15), fill=GRAY_LT, radius=0.09,
    text=[[("✗  Never goes on the blockchain", {"bold": True, "size": 14, "color": RED})],
          [("• Medical records or documents", {"size": 12.5, "color": GRAY})],
          [("• Names, IDs or any personal data", {"size": 12.5, "color": GRAY})],
          [("• Anything that could identify a patient", {"size": 12.5, "color": GRAY})]],
    align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE, space_after=5)
vflow(s, Inches(7.3), Inches(1.85), Inches(5.0),
      ["📜  Consent / access event", "#️⃣  Hash — digital fingerprint",
       "⛓  Stored on Polygon blockchain", "🔎  Anyone can verify later"],
      Inches(0.78), gap=Inches(0.32), size=12.5,
      fills=[GRAY_LT, BLUE_LT, NAVY, TEAL_LT], tcolors=[NAVY, NAVY, WHITE, NAVY])
textbox(s, MARGIN, Inches(6.5), Inches(12.2), Inches(0.4),
        [[("Why?  ", {"bold": True, "color": NAVY, "size": 12.5}),
          ("a hospital can quietly edit its own database — it cannot edit a public "
           "blockchain.", {"color": GRAY, "size": 12.5})]], align=PP_ALIGN.CENTER)
notes(s, "• Clear the misconception: we do NOT store medical data on a blockchain.\n"
         "• Left: what goes on-chain vs never. Right: the four-step flow.\n"
         "• If the log is edited, hashes stop matching — tampering shows.\n"
         "• Transition: the full technology stack.")

# ============================================================ 16 · TECH STACK
s = new_slide(prs, "Technology Stack", "Grouped by layer — and why each was chosen")
tech = [("⚛️", "Frontend", "React / Next.js", "one code base, both portals"),
        ("☕", "Backend APIs", "Spring Boot", "reliable, secure REST APIs"),
        ("🐍", "AI services", "Python + LangChain", "the standard RAG ecosystem"),
        ("🐘", "Database", "PostgreSQL", "JSON + tables + vectors in one"),
        ("🧭", "Vector search", "pgvector", "consent filter in the same query"),
        ("🤖", "LLM", "Hosted API (swappable)", "no training; no vendor lock-in"),
        ("⛓", "Blockchain", "Polygon (testnet)", "low-cost, well documented"),
        ("📋", "Health standard", "HL7 FHIR R4", "global standard, Synthea-native"),
        ("🐳", "Deployment", "Docker", "same setup on every machine")]
for i, (em, layer, t, why) in enumerate(tech):
    x = MARGIN + (i % 3) * Inches(4.12)
    y = Inches(1.85) + (i // 3) * Inches(1.62)
    box(s, x, y, Inches(3.92), Inches(1.42), fill=BLUE_LT if (i//3) % 2 == 0 else TEAL_LT,
        radius=0.09, text=None)
    icon_circle(s, x + Inches(0.16), y + Inches(0.15), Inches(0.58), em, fill=WHITE, esize=17)
    textbox(s, x + Inches(0.88), y + Inches(0.12), Inches(2.95), Inches(0.3), layer.upper(),
            size=9.5, color=GRAY_MED, bold=True)
    textbox(s, x + Inches(0.88), y + Inches(0.4), Inches(2.95), Inches(0.4), t,
            size=14, color=NAVY, bold=True)
    textbox(s, x + Inches(0.2), y + Inches(0.9), Inches(3.55), Inches(0.45), why,
            size=10.5, color=GRAY)
notes(s, "• Pick three to talk about: Spring Boot for APIs, Python for AI, PostgreSQL "
         "doing triple duty.\n"
         "• The LLM is behind an interface — provider can change anytime.\n"
         "• Transition: the build plan.")

# ============================================================ 17 · ROADMAP (timeline)
s = new_slide(prs, "Implementation Roadmap", "Nine stages across the year")
TLY = Inches(4.05)
line = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.75), TLY - Pt(2), Inches(11.85), Pt(4))
set_fill(line, BORDER)
phases = [("Research", "literature & gap", GREEN, "DONE"),
          ("Dataset", "Synthea analysis", GREEN, "DONE"),
          ("Parser", "parse · validate", ORANGE, "NOW"),
          ("Database", "schema + load", GRAY_MED, ""),
          ("APIs", "REST + consent", GRAY_MED, ""),
          ("Frontend", "portals", GRAY_MED, ""),
          ("AI", "RAG + chat", GRAY_MED, ""),
          ("Blockchain", "audit anchor", GRAY_MED, ""),
          ("Testing", "evaluation", GRAY_MED, "")]
DOT = Inches(0.30)
for i, (t, d, c, st) in enumerate(phases):
    cx = Inches(0.95) + i * Inches(1.40)
    dot = s.shapes.add_shape(MSO_SHAPE.OVAL, cx, TLY - DOT/2, DOT, DOT)
    set_fill(dot, c); dot.shadow.inherit = False
    dot.line.color.rgb = WHITE; dot.line.width = Pt(1.5)
    above = (i % 2 == 0)
    ty = TLY - Inches(1.45) if above else TLY + Inches(0.35)
    tick = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, cx + DOT//2,
                                  TLY - Inches(0.42) if above else TLY + Inches(0.17),
                                  cx + DOT//2, TLY - Inches(0.15) if above else TLY + Inches(0.35))
    tick.line.color.rgb = BORDER; tick.line.width = Pt(1)
    tb_y = ty
    textbox(s, cx - Inches(0.62), tb_y, Inches(1.6), Inches(0.35), f"{i+1} · {t}",
            size=12.5, color=NAVY, bold=True, align=PP_ALIGN.CENTER)
    textbox(s, cx - Inches(0.62), tb_y + Inches(0.32), Inches(1.6), Inches(0.3), d,
            size=10, color=GRAY_MED, align=PP_ALIGN.CENTER)
    if st:
        chip(s, cx - Inches(0.3), tb_y + Inches(0.66), Inches(0.95), Inches(0.26), st,
             fill=c, size=9)
leg = [("DONE", GREEN), ("IN PROGRESS", ORANGE), ("UPCOMING", GRAY_MED)]
lx = Inches(4.2)
for t, c in leg:
    dot = s.shapes.add_shape(MSO_SHAPE.OVAL, lx, Inches(6.35), Inches(0.18), Inches(0.18))
    set_fill(dot, c); dot.shadow.inherit = False
    textbox(s, lx + Inches(0.26), Inches(6.29), Inches(1.6), Inches(0.3), t,
            size=10.5, color=GRAY_MED)
    lx += Inches(1.85)
textbox(s, MARGIN, Inches(1.7), Inches(12.2), Inches(0.4),
        [[("Order matters:  ", {"bold": True, "color": NAVY, "size": 12.5}),
          ("data before AI · consent before the AI touches data · blockchain wraps it all "
           "at the end.", {"color": GRAY, "size": 12.5})]], align=PP_ALIGN.CENTER)
notes(s, "• Stages 1–2 done; this review is the stage-1 output.\n"
         "• Parser is in progress right now.\n"
         "• Consent is built before the AI is connected — by design.\n"
         "• Transition: what everyone gets at the end.")

# ============================================================ 18 · OUTCOMES
s = new_slide(prs, "Expected Outcomes", "What each stakeholder gets")
outs = [("🧑", "Patient", "Owns one complete\nhistory + access log"),
        ("🩺", "Doctor", "Consented history +\nAI summary, not 50 PDFs"),
        ("🏥", "Hospital", "Standard exchange,\nno vendor lock-in"),
        ("🔬", "Researchers", "Open reference design\n+ measured results"),
        ("🌐", "Ecosystem", "A patient-first\nworking template")]
for i, (em, t, d) in enumerate(outs):
    vcard(s, Inches(0.55) + i * Inches(2.48), Inches(2.0), Inches(2.32), Inches(2.7),
          em, t, d, fill=BLUE_LT if i % 2 == 0 else TEAL_LT)
banner(s, Inches(5.3),
       [("Deliverables:  ", {"bold": True, "color": WHITE, "size": 13.5}),
        ("a working PulseOS prototype on Synthea data  +  a research paper on "
         "consent-controlled AI access to health records.", {"color": W_INK, "size": 13})],
       h=Inches(0.85))
notes(s, "• One line per stakeholder.\n"
         "• Doctor line lands best: a summary instead of a pile of PDFs.\n"
         "• Close on the two deliverables: prototype + paper.\n"
         "• Transition: what comes after this year.")

# ============================================================ 19 · FUTURE SCOPE
s = new_slide(prs, "Future Scope", "Beyond this year — staged extensions")
future = [("🇮🇳", "ABDM / ABHA", "plug into India's national health IDs"),
          ("⌚", "Wearables & IoT", "live vitals into the record"),
          ("🔌", "Public FHIR APIs", "third-party apps on top"),
          ("📈", "Predictive analytics", "risk alerts from timelines"),
          ("🗣", "Voice assistant", "talk to the health copilot"),
          ("🏥", "Real hospitals", "pilot with live systems"),
          ("📱", "Mobile app", "native patient experience"),
          ("🆔", "Decentralized ID", "self-sovereign identity")]
for i, (em, t, d) in enumerate(future):
    x = MARGIN + (i % 4) * Inches(3.09)
    y = Inches(2.0) + (i // 4) * Inches(2.1)
    vcard(s, x, y, Inches(2.9), Inches(1.9), em, t, d,
          fill=BLUE_LT if (i + i // 4) % 2 == 0 else TEAL_LT, tsize=12.5, ssize=10)
textbox(s, MARGIN, Inches(6.35), Inches(12.2), Inches(0.4),
        "None of these are needed for this year's deliverables — they build on the same platform.",
        size=11.5, color=GRAY_MED, align=PP_ALIGN.CENTER)
notes(s, "• Deliberately out of this year's scope — say so.\n"
         "• ABDM integration is the most natural next step for India.\n"
         "• Transition: references.")

# ============================================================ 20 · REFERENCES
s = new_slide(prs, "References", "IEEE format — papers studied for this project")
refs = [
 '[1] Y. Kabak et al., "FHIR-RAG-MEDS: Integrating HL7 FHIR with retrieval-augmented large '
 'language models for enhanced medical decision support," AI (MDPI), vol. 7, 2026.',
 '[2] Y. Li, H. Wang, H. Z. Yerebakan, Y. Shinagawa, and Y. Luo, "Enhancing health data '
 'interoperability with large language models: A FHIR study," Northwestern Univ. / Siemens '
 'Medical Solutions, 2023.',
 '[3] L. Grau, J. Urrunaga, and J. Santisteban, "WiraChain: A blockchain and FHIR-based '
 'platform for improving clinical data interoperability in healthcare," Frontiers in Public '
 'Health, vol. 14, art. 1746772, Feb. 2026.',
 '[4] K. Chafik, M. Hanine, A. Ouaguid, and S. Alshuhri, "Blockchain technology to enhance '
 'clinical data management in healthcare: A systematic literature review," Blockchain in '
 'Healthcare Today, vol. 9, art. 471, Mar. 2026.',
 '[5] S. Phuyal, M. Bhandari, R. Bista, and J. C. Ferreira, "HL7 FHIR consent for healthcare '
 'data sharing: Challenges, opportunities and integrity implications," Int. J. Medical '
 'Informatics, vol. 214, art. 106405, 2026.',
 '[6] S. Phuyal, M. Bhandari, R. Bista, and J. C. Ferreira, "Blockchain-based dynamic and '
 'revocable consent for secondary health data use: Systematic review," JMIR Medical '
 'Informatics, vol. 14, art. e88536, 2026.',
 '[7] J.-F. Wang et al., "An innovative X-RAG technique combined with GPT-4o for summarizing '
 'medical information from EHR and EMR to assist doctors in clinical decision-making," '
 'Health Informatics Journal, vol. 31, no. 3, pp. 1–16, 2025.',
 '[8] D. K. Mishra and P. S. Mehra, "Enhancing interoperability and scalability in '
 'DiabeticChain: An integrative architecture using IPFS, Polygon, and HL7/FHIR," Computers '
 'and Electrical Engineering, vol. 129, art. 110835, 2026.',
 '[9] P. Randine, E. Salant, M. Muzny, and L. Pape-Haugaard, "Consent management system on '
 'patient-generated health data," in MEDINFO 2023, Studies in Health Technology and '
 'Informatics, IOS Press, 2024, pp. 204–208.',
 '[10] B. Houtan, A. S. Hafid, and D. Makrakis, "A survey on blockchain-based self-sovereign '
 'patient identity in healthcare," IEEE Access, vol. 8, pp. 90478–90494, 2020.',
 '[11] M. Adil et al., "Healthcare Internet of Things: Security threats, challenges, and '
 'future research directions," IEEE Internet of Things Journal, vol. 11, no. 11, '
 'pp. 19046–19069, Jun. 2024.',
]
def ref_col(x, items):
    tb = s.shapes.add_textbox(x, Inches(1.75), Inches(5.95), Inches(5.1))
    tf = tb.text_frame; tf.word_wrap = True
    for i, rtxt in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(8); p.line_spacing = 1.02
        run = p.add_run(); run.text = rtxt
        run.font.size = Pt(10); run.font.color.rgb = GRAY
ref_col(MARGIN, refs[:6])
ref_col(Inches(6.85), refs[6:])
notes(s, "• Six primary papers [1]–[6] shaped the design; [7]–[11] are supporting.\n"
         "• All papers are from our own literature folder.\n"
         "• Thank the panel and invite questions.")

out = "/Users/sanket/Documents/Projects/Pulse OS/PulseOS_Review1.pptx"
prs.save(out)
print("Saved", out, "| slides:", len(prs.slides._sldIdLst))
