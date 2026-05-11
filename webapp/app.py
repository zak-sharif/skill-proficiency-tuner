"""
Skill Proficiency Threshold Tuner — Streamlit webapp.

Lets you tune L1/L2/L3/L4 thresholds against the Fall 2025 backtest data and
see the distribution of skill attainment per course in real time.

Run from project root:
    streamlit run webapp/app.py

Inputs (built by scripts/build_fact_table.py):
    data/backtest/criterion_facts.parquet
    data/backtest/student_enrollments.parquet
    data/backtest/skill_meta.parquet
"""

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(layout="wide", page_title="Skill Proficiency Tuner")

# Path resolution: works whether run from repo root, webapp/, or via Streamlit Cloud
APP_DIR = Path(__file__).resolve().parent
for candidate in [APP_DIR.parent / "data" / "backtest",
                  APP_DIR / "data" / "backtest",
                  Path("data") / "backtest"]:
    if (candidate / "criterion_facts.parquet").exists():
        BACKTEST_DIR = candidate
        break
else:
    st.error("Could not locate criterion_facts.parquet — check deployment data layout.")
    st.stop()

# ── Optional password gate (set APP_PASSWORD in Streamlit secrets to enable) ──
def check_password():
    try:
        expected = st.secrets["APP_PASSWORD"]
    except (KeyError, FileNotFoundError, Exception):
        return True  # no password configured → open access (local dev)
    if st.session_state.get("auth_ok"):
        return True
    pw = st.text_input("Password", type="password")
    if pw and pw == expected:
        st.session_state["auth_ok"] = True
        st.rerun()
    elif pw:
        st.error("Incorrect password")
    return False

if not check_password():
    st.stop()

# ────────────────────────────────────────────────────────────────────
# Data loading
# ────────────────────────────────────────────────────────────────────

@st.cache_data
def load_data():
    facts = pd.read_parquet(BACKTEST_DIR / "criterion_facts.parquet")
    enrollments = pd.read_parquet(BACKTEST_DIR / "student_enrollments.parquet")
    skills = pd.read_parquet(BACKTEST_DIR / "skill_meta.parquet")
    return facts, enrollments, skills


facts, enrollments, skills_meta = load_data()

# ────────────────────────────────────────────────────────────────────
# Sidebar — knobs
# ────────────────────────────────────────────────────────────────────

st.sidebar.markdown("## Threshold Knobs")
st.sidebar.caption("Sliders below re-run the calculation in real time.")

# Term filter
all_terms = sorted(facts["term"].unique().tolist()) if "term" in facts.columns else ["Fall 2025"]
selected_terms = st.sidebar.multiselect(
    "Term(s)",
    all_terms,
    default=all_terms,
    help="Pick one or both. The same student in both terms is treated as separate observations.",
)
if not selected_terms:
    st.warning("Select at least one term.")
    st.stop()
facts = facts[facts["term"].isin(selected_terms)]
if "term" in enrollments.columns:
    enrollments = enrollments[enrollments["term"].isin(selected_terms)]

all_courses = sorted(facts["course"].unique().tolist())
default_courses = ["DMARK I", "DMARK IV", "CYBER I", "CYBER III", "COMPS II", "COMPS III"]
default_courses = [c for c in default_courses if c in all_courses]

selected_courses = st.sidebar.multiselect(
    "Courses to display",
    all_courses,
    default=default_courses,
    help="Per-course pivot tables shown below for these courses.",
)

capstone_courses = st.sidebar.multiselect(
    "Capstone courses",
    all_courses,
    default=[],
    help="Used by the 'require capstone-course criterion' toggle below.",
)

include_in_calc = st.sidebar.multiselect(
    "Courses to include in calculation",
    all_courses,
    default=all_courses,
    help="Cross-course aggregation: which courses' criteria can contribute.",
)

enable_l4 = st.sidebar.checkbox("Enable L4 (400-level mastery)", value=False)

calc_scope = st.sidebar.radio(
    "Proficiency scope",
    ["Cross-course (full Rize journey)", "Single-course (this course only)"],
    index=0,
    help=(
        "Cross-course: a student's level for a skill aggregates criteria from "
        "every course they took. Single-course: each course is evaluated "
        "independently — the same student can have different levels for the "
        "same skill in different courses."
    ),
)
SCOPE_SINGLE = calc_scope.startswith("Single")

# Path filter
path_filter = st.sidebar.multiselect(
    "Skill path filter",
    ["Benchmark", "LO", "Both"],
    default=["Benchmark", "LO", "Both"],
    help="Filter the per-skill table to skills connected via Benchmark (Path A), LO (Path B), or Both.",
)

LEVEL_DEFAULTS = {
    1: dict(min_meets=4, min_exceeds=1, min_outstanding=0,
            source_min_level=0, enrolled_min_level=0,
            fp_min_rating=0, require_capstone=False),
    2: dict(min_meets=3, min_exceeds=2, min_outstanding=0,
            source_min_level=200, enrolled_min_level=200,
            fp_min_rating=0, require_capstone=False),
    3: dict(min_meets=2, min_exceeds=2, min_outstanding=1,
            source_min_level=300, enrolled_min_level=300,
            fp_min_rating=0, require_capstone=False),
    4: dict(min_meets=2, min_exceeds=2, min_outstanding=2,
            source_min_level=400, enrolled_min_level=400,
            fp_min_rating=4, require_capstone=True),
}

LEVEL_OPTS = [0, 200, 300, 400]
LEVEL_LABELS = {0: "Any", 200: "200+", 300: "300+", 400: "400+"}
RATING_OPTS = [0, 3, 4, 5]
RATING_LABELS = {0: "None", 3: "≥ Meets", 4: "≥ Exceeds", 5: "Outstanding only"}

# ── Skill points knobs ──
with st.sidebar.expander("Skill Points: rating values", expanded=False):
    pt_outstanding = st.number_input("Outstanding (ord 5)", value=5.0, step=0.5, key="pt_o")
    pt_exceeds = st.number_input("Exceeds Standard (ord 4)", value=4.0, step=0.5, key="pt_e")
    pt_meets = st.number_input("Meets Standard (ord 3)", value=3.0, step=0.5, key="pt_m")
    pt_approaches = st.number_input("Approaches Standard (ord 2)", value=1.0, step=0.5, key="pt_a")
    pt_below = st.number_input("Below Standard (ord 1)", value=0.0, step=0.5, key="pt_b")
    pt_none = st.number_input("No Evidence (ord 0)", value=0.0, step=0.5, key="pt_n")

with st.sidebar.expander("Skill Points: course-level multipliers", expanded=False):
    mult_100 = st.number_input("100-level ×", value=1.0, step=0.1, key="mult100")
    mult_200 = st.number_input("200-level ×", value=1.5, step=0.1, key="mult200")
    mult_300 = st.number_input("300-level ×", value=2.0, step=0.1, key="mult300")
    mult_400 = st.number_input("400-level ×", value=2.5, step=0.1, key="mult400")
    mult_500p = st.number_input("500+-level ×", value=3.0, step=0.1, key="mult500p")

with st.sidebar.expander("Skill Points: assignment-type multipliers", expanded=False):
    mult_project = st.number_input("Project criterion ×", value=1.5, step=0.1, key="multproj")
    mult_fp = st.number_input("Final-project criterion ×", value=1.0, step=0.1, key="multfp",
                              help="Applied on top of project ×. Set to 1.0 to disable.")

RATING_VALUES = {5: pt_outstanding, 4: pt_exceeds, 3: pt_meets,
                 2: pt_approaches, 1: pt_below, 0: pt_none}

def level_multiplier(course_level):
    if course_level >= 500: return mult_500p
    if course_level >= 400: return mult_400
    if course_level >= 300: return mult_300
    if course_level >= 200: return mult_200
    return mult_100

configs = {}
for lvl in [1, 2, 3, 4]:
    if lvl == 4 and not enable_l4:
        configs[lvl] = {"enabled": False}
        continue
    with st.sidebar.expander(f"L{lvl} rules", expanded=(lvl <= 3)):
        d = LEVEL_DEFAULTS[lvl]
        cfg = {"enabled": True}
        cfg["min_meets"] = st.number_input(
            "Min Meets+ count", 0, 30, d["min_meets"], key=f"m{lvl}"
        )
        cfg["min_exceeds"] = st.number_input(
            "Min Exceeds+ count", 0, 30, d["min_exceeds"], key=f"e{lvl}"
        )
        cfg["min_outstanding"] = st.number_input(
            "Min Outstanding count", 0, 30, d["min_outstanding"], key=f"o{lvl}"
        )
        cfg["source_min_level"] = st.selectbox(
            "Criteria must come from",
            LEVEL_OPTS,
            format_func=lambda x: f"{LEVEL_LABELS[x]} courses",
            index=LEVEL_OPTS.index(d["source_min_level"]),
            key=f"src{lvl}",
        )
        cfg["enrolled_min_level"] = st.selectbox(
            "Student enrolled in",
            LEVEL_OPTS,
            format_func=lambda x: f"{LEVEL_LABELS[x]} courses",
            index=LEVEL_OPTS.index(d["enrolled_min_level"]),
            key=f"enr{lvl}",
        )
        cfg["fp_min_rating"] = st.selectbox(
            "Final-project rating requirement",
            RATING_OPTS,
            format_func=lambda x: RATING_LABELS[x],
            index=RATING_OPTS.index(d["fp_min_rating"]),
            key=f"fp{lvl}",
            help="Require ≥1 final-project criterion at this rating.",
        )
        cfg["require_capstone"] = st.checkbox(
            "Require ≥1 criterion from a capstone course",
            value=d["require_capstone"],
            key=f"cap{lvl}",
        )
        configs[lvl] = cfg

# ────────────────────────────────────────────────────────────────────
# Calculation
# ────────────────────────────────────────────────────────────────────


def qualifying_pairs_for_level(facts_df, enrollments_df, capstones, cfg):
    """Return MultiIndex (student_id, skill_id) of pairs qualifying for this level."""
    src_facts = facts_df[facts_df["course_level"] >= cfg["source_min_level"]]
    if src_facts.empty:
        return pd.MultiIndex.from_tuples([], names=["student_id", "skill_id"])

    counts = src_facts.assign(
        meets=(src_facts["ordinal"] >= 3).astype(int),
        exceeds=(src_facts["ordinal"] >= 4).astype(int),
        outstanding=(src_facts["ordinal"] >= 5).astype(int),
    ).groupby(["student_id", "skill_id"])[["meets", "exceeds", "outstanding"]].sum()

    qualifies = (
        (counts["meets"] >= cfg["min_meets"])
        & (counts["exceeds"] >= cfg["min_exceeds"])
        & (counts["outstanding"] >= cfg["min_outstanding"])
    )

    # Enrollment check
    if cfg["enrolled_min_level"] > 0:
        elig_students = set(
            enrollments_df.loc[
                enrollments_df["course_level"] >= cfg["enrolled_min_level"],
                "student_id",
            ]
        )
        sid_idx = qualifies.index.get_level_values("student_id")
        enroll_mask = pd.Series(sid_idx.isin(elig_students), index=qualifies.index)
        qualifies &= enroll_mask

    # Final-project rating check
    if cfg["fp_min_rating"] > 0:
        fp = facts_df[
            facts_df["is_final_project"]
            & (facts_df["ordinal"] >= cfg["fp_min_rating"])
            & (facts_df["course_level"] >= cfg["source_min_level"])
        ]
        fp_pairs = fp.groupby(["student_id", "skill_id"]).size().index
        fp_mask = pd.Series(qualifies.index.isin(fp_pairs), index=qualifies.index)
        qualifies &= fp_mask

    # Capstone check
    if cfg["require_capstone"] and capstones:
        cap = facts_df[facts_df["course"].isin(capstones)]
        cap_pairs = cap.groupby(["student_id", "skill_id"]).size().index
        cap_mask = pd.Series(qualifies.index.isin(cap_pairs), index=qualifies.index)
        qualifies &= cap_mask

    return qualifies[qualifies].index


def assign_levels(facts_df, enrollments_df, capstones, configs):
    """Return Series indexed by (student_id, skill_id) → highest level."""
    base_pairs = facts_df.groupby(["student_id", "skill_id"]).size().index
    levels = pd.Series(0, index=base_pairs, name="level")

    for lvl in [1, 2, 3, 4]:
        cfg = configs.get(lvl)
        if not cfg or not cfg.get("enabled"):
            continue
        qual = qualifying_pairs_for_level(facts_df, enrollments_df, capstones, cfg)
        # Bump levels — a higher tier always overrides a lower one
        match = levels.index.isin(qual)
        levels.loc[match] = np.maximum(levels.loc[match].values, lvl)

    return levels


# Filter facts to those in courses we want to include in the calculation
filtered_facts = facts[facts["course"].isin(include_in_calc)]
filtered_enrollments = enrollments[enrollments["course"].isin(include_in_calc)]


def compute_proficiency(scope_single, facts_df, enr_df, capstones, configs):
    """Returns DataFrame with student_id, skill_id, level (and `course` if single)."""
    if not scope_single:
        levels = assign_levels(facts_df, enr_df, capstones, configs)
        return levels.reset_index()  # student_id, skill_id, level
    out = []
    for course in facts_df["course"].unique():
        c_facts = facts_df[facts_df["course"] == course]
        c_enr = enr_df[enr_df["course"] == course]
        c_levels = assign_levels(c_facts, c_enr, capstones, configs)
        d = c_levels.reset_index()
        d["course"] = course
        out.append(d)
    if not out:
        return pd.DataFrame(columns=["student_id", "skill_id", "course", "level"])
    return pd.concat(out, ignore_index=True)


with st.spinner("Computing levels..."):
    levels_df = compute_proficiency(
        SCOPE_SINGLE, filtered_facts, filtered_enrollments, capstone_courses, configs
    )

# Annotate with skill metadata
path_cols = [c for c in ["skill_id", "skill_name", "path_overall", "path_per_course"] if c in skills_meta.columns]
levels_df = levels_df.merge(skills_meta[path_cols], on="skill_id", how="left")

# ────────────────────────────────────────────────────────────────────
# Top — summary metrics
# ────────────────────────────────────────────────────────────────────

st.title("Skill Proficiency Threshold Tuner")
scope_label = "Single-course" if SCOPE_SINGLE else "Cross-course (Rize journey)"
n_students_selected = enrollments["student_id"].nunique() if len(enrollments) else 0
n_facts_selected = len(facts)
term_label = " + ".join(selected_terms)
st.caption(
    f"**{term_label}** · {n_students_selected:,} students · "
    f"{n_facts_selected:,} matched criteria · scope: **{scope_label}**"
)

obs_label = "Student-skill-course observations" if SCOPE_SINGLE else "Student-skill pairs"
dist = levels_df["level"].value_counts().reindex([0, 1, 2, 3, 4], fill_value=0)
total = int(dist.sum())
cols = st.columns(6)
cols[0].metric(obs_label, f"{total:,}")
cols[1].metric("L0 only", f"{dist[0]:,}", f"{dist[0]/total:.0%}" if total else "—")
cols[2].metric("≥ L1", f"{dist[[1,2,3,4]].sum():,}",
               f"{dist[[1,2,3,4]].sum()/total:.0%}" if total else "—")
cols[3].metric("≥ L2", f"{dist[[2,3,4]].sum():,}",
               f"{dist[[2,3,4]].sum()/total:.0%}" if total else "—")
cols[4].metric("≥ L3", f"{dist[[3,4]].sum():,}",
               f"{dist[[3,4]].sum()/total:.0%}" if total else "—")
if enable_l4:
    cols[5].metric("L4", f"{dist[4]:,}", f"{dist[4]/total:.0%}" if total else "—")

# ────────────────────────────────────────────────────────────────────
# Per-skill summary
# ────────────────────────────────────────────────────────────────────

st.markdown("### Per-skill distribution")
st.caption(
    "**Path** column: how the skill connects to rubric criteria — "
    "**Benchmark** = via unit-level `benchmarkSkills` (Path A); "
    "**LO** = via Learning Outcomes (Path B); **Both** = both. "
    + ("Rows are per (skill, course) under single-course scope." if SCOPE_SINGLE else "Rows aggregate across all enrolled courses.")
)
group_cols = ["skill_id", "skill_name"] + (["course"] if SCOPE_SINGLE else [])
skill_summary = (
    levels_df.groupby(group_cols + ["level"]).size().unstack(fill_value=0)
)
for lvl in [0, 1, 2, 3, 4]:
    if lvl not in skill_summary.columns:
        skill_summary[lvl] = 0
skill_summary = skill_summary.reset_index()
skill_summary["Total"] = skill_summary[[0, 1, 2, 3, 4]].sum(axis=1)
skill_summary["≥L1"] = skill_summary[[1, 2, 3, 4]].sum(axis=1)
skill_summary["≥L2"] = skill_summary[[2, 3, 4]].sum(axis=1)
skill_summary["≥L3"] = skill_summary[[3, 4]].sum(axis=1)
skill_summary["%≥L1"] = (skill_summary["≥L1"] / skill_summary["Total"] * 100).round(1)
skill_summary["%≥L2"] = (skill_summary["≥L2"] / skill_summary["Total"] * 100).round(1)
skill_summary["%≥L3"] = (skill_summary["≥L3"] / skill_summary["Total"] * 100).round(1)
if enable_l4:
    skill_summary["%L4"] = (skill_summary[4] / skill_summary["Total"] * 100).round(1)

# Merge path classification
if "path_overall" in skills_meta.columns:
    skill_summary = skill_summary.merge(
        skills_meta[["skill_id", "path_overall", "path_per_course"]],
        on="skill_id", how="left",
    )

skill_summary = skill_summary.rename(
    columns={0: "L0", 1: "L1", 2: "L2", 3: "L3", 4: "L4",
             "skill_name": "Skill", "path_overall": "Path",
             "path_per_course": "Path (per course)"}
).drop(columns=["skill_id"])

display_cols = ["Skill"]
if SCOPE_SINGLE:
    display_cols.append("course")
display_cols += ["Path", "Total", "L0", "L1", "L2", "L3"]
if enable_l4:
    display_cols.append("L4")
display_cols += ["≥L1", "≥L2", "≥L3", "%≥L1", "%≥L2", "%≥L3"]
if enable_l4:
    display_cols.append("%L4")
display_cols.append("Path (per course)")
display_cols = [c for c in display_cols if c in skill_summary.columns]
skill_summary = skill_summary.rename(columns={"course": "Course"})
display_cols = [c if c != "course" else "Course" for c in display_cols]
skill_summary = skill_summary.sort_values("%≥L1", ascending=False)
if "Path" in skill_summary.columns and path_filter:
    skill_summary_view = skill_summary[skill_summary["Path"].isin(path_filter)]
else:
    skill_summary_view = skill_summary
st.dataframe(skill_summary_view[display_cols], use_container_width=True, height=380)

# ────────────────────────────────────────────────────────────────────
# Per-course pivots
# ────────────────────────────────────────────────────────────────────

st.markdown("### Per-course pivots")
st.caption(
    "Counts show students at *exactly* this level (highest tier achieved). "
    "Levels are monotonic — a student at L3 also has L1 and L2 by inclusion."
)


def course_ceiling_for(course):
    lvl_to_cap = filtered_enrollments.set_index("course")["course_level"].to_dict()
    cl = lvl_to_cap.get(course, 100)
    if enable_l4 and cl >= 400:
        return 4
    if cl >= 300:
        return 3
    if cl >= 200:
        return 2
    return 1


def build_course_pivot(course):
    # Students enrolled in this course
    course_students = set(
        enrollments.loc[enrollments["course"] == course, "student_id"]
    )
    # Skills mapped in this course (sorted by criterion count desc)
    course_facts_in = facts[facts["course"] == course]
    skill_order = (
        course_facts_in.groupby("skill_id")
        .size()
        .sort_values(ascending=False)
        .index.tolist()
    )
    if not skill_order:
        return None
    skill_id_to_name = dict(
        zip(skills_meta["skill_id"], skills_meta["skill_name"])
    )

    # Build a lookup for (student, skill) → level for this course's view
    if SCOPE_SINGLE:
        sub = levels_df[levels_df["course"] == course]
    else:
        sub = levels_df  # cross-course: all rows are at student-skill granularity
    lookup = sub.set_index(["student_id", "skill_id"])["level"].to_dict()

    ceiling = course_ceiling_for(course)
    levels_to_show = [None, 0, 1] + ([2] if ceiling >= 2 else []) + (
        [3] if ceiling >= 3 else []
    ) + ([4] if ceiling >= 4 else [])
    label_for = {None: "—", 0: "L0", 1: "L1", 2: "L2", 3: "L3", 4: "L4"}

    rows = {label_for[l]: [] for l in levels_to_show}
    rows["Total"] = []

    skill_names_ordered = [skill_id_to_name.get(s, s) for s in skill_order]

    from collections import Counter
    for sid in skill_order:
        per_skill_levels = []
        students_with_data = 0
        for uid in course_students:
            lvl = lookup.get((uid, sid))
            if lvl is not None:
                per_skill_levels.append(min(lvl, ceiling))
                students_with_data += 1

        no_data = len(course_students) - students_with_data
        c = Counter(per_skill_levels)

        for l in levels_to_show:
            if l is None:
                rows[label_for[l]].append(no_data)
            else:
                rows[label_for[l]].append(c.get(l, 0))
        rows["Total"].append(len(course_students))

    df = pd.DataFrame(rows, index=skill_names_ordered).T
    df["Average %"] = ""
    # Add percentage rows
    total_count = len(course_students)
    for l in levels_to_show:
        if l is None:
            continue
        label = label_for[l]
        pcts = [c / total_count * 100 if total_count else 0 for c in df.loc[label][:-1]]
        avg = sum(pcts) / len(pcts) if pcts else 0
        pct_row = [f"{p:.1f}%" for p in pcts] + [f"{avg:.1f}%"]
        df.loc[f"{label} %"] = pct_row

    return df


pivot_tabs = st.tabs(selected_courses) if selected_courses else []
for tab, course in zip(pivot_tabs, selected_courses):
    with tab:
        pv = build_course_pivot(course)
        if pv is None:
            st.info(f"No skill data for {course}.")
        else:
            st.dataframe(pv, use_container_width=True)

# ────────────────────────────────────────────────────────────────────
# Skill Points
# ────────────────────────────────────────────────────────────────────

def compute_skill_points(facts_df):
    if facts_df.empty:
        return pd.DataFrame(columns=["student_id", "skill_id", "skill_name", "course", "points", "criteria"])
    df = facts_df.copy()
    # Drop rows with ordinal -1 (unmappable rating)
    df = df[df["ordinal"] >= 0]
    df["rating_value"] = df["ordinal"].map(RATING_VALUES).fillna(0)
    df["level_mult"] = df["course_level"].apply(level_multiplier)
    df["proj_mult"] = np.where(df["assignment_type"] == "project", mult_project, 1.0)
    df["fp_mult"] = np.where(df["is_final_project"], mult_fp, 1.0)
    df["points"] = df["rating_value"] * df["level_mult"] * df["proj_mult"] * df["fp_mult"]
    out = (
        df.groupby(["student_id", "skill_id", "skill_name", "course"], as_index=False)
        .agg(points=("points", "sum"), criteria=("points", "count"))
    )
    return out


points_per_student = compute_skill_points(filtered_facts)

st.markdown("### Skill Points — average per student, per skill, per course")
st.caption(
    "For each (student, skill, course): `points = Σ over matched criteria of "
    "rating_value × course-level multiplier × project multiplier × final-project multiplier`. "
    "Then averaged across students in that course. Tune values in the sidebar."
)

if not selected_courses:
    st.info("Select at least one course above to see skill-point breakdowns.")
elif points_per_student.empty:
    st.info("No matched criteria for the current filters.")
else:
    sp_tabs = st.tabs(selected_courses)
    for tab, course in zip(sp_tabs, selected_courses):
        with tab:
            sub = points_per_student[points_per_student["course"] == course]
            if sub.empty:
                st.info(f"No skill-point data for {course}.")
                continue
            agg = (
                sub.groupby(["skill_id", "skill_name"], as_index=False)
                .agg(
                    students=("points", "count"),
                    mean_points=("points", "mean"),
                    median_points=("points", "median"),
                    p25=("points", lambda s: s.quantile(0.25)),
                    p75=("points", lambda s: s.quantile(0.75)),
                    avg_criteria=("criteria", "mean"),
                )
                .sort_values("mean_points", ascending=False)
            )
            agg = agg.rename(columns={
                "skill_name": "Skill",
                "students": "Students",
                "mean_points": "Avg points / student",
                "median_points": "Median points",
                "p25": "P25", "p75": "P75",
                "avg_criteria": "Avg criteria matched",
            }).drop(columns=["skill_id"])
            for col in ["Avg points / student", "Median points", "P25", "P75", "Avg criteria matched"]:
                agg[col] = agg[col].round(2)
            st.dataframe(agg, use_container_width=True, height=380)


# ────────────────────────────────────────────────────────────────────
# Active rules summary
# ────────────────────────────────────────────────────────────────────

with st.expander("Active rule summary"):
    rows = []
    for lvl in [1, 2, 3, 4]:
        cfg = configs.get(lvl, {})
        if not cfg.get("enabled"):
            rows.append({"Level": f"L{lvl}", "Rule": "(disabled)"})
            continue
        parts = []
        parts.append(f"≥{cfg['min_meets']} Meets+")
        parts.append(f"≥{cfg['min_exceeds']} Exceeds+")
        if cfg["min_outstanding"] > 0:
            parts.append(f"≥{cfg['min_outstanding']} Outstanding")
        parts.append(f"from {LEVEL_LABELS[cfg['source_min_level']]} courses")
        parts.append(f"enrolled in {LEVEL_LABELS[cfg['enrolled_min_level']]} courses")
        if cfg["fp_min_rating"] > 0:
            parts.append(f"+ final-project criterion at {RATING_LABELS[cfg['fp_min_rating']]}")
        if cfg["require_capstone"]:
            parts.append("+ ≥1 capstone-course criterion")
        rows.append({"Level": f"L{lvl}", "Rule": "; ".join(parts)})
    st.table(pd.DataFrame(rows))

st.caption(
    "Mastery is treated as Outstanding-equivalent (top-of-scale) on competency-scale rubrics. "
    "Final-project detection: assignment title contains 'Final Project' (excluding discussions)."
)
