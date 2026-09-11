from flask import Flask, render_template, request, jsonify, send_file, abort
import pandas as pd
import os
import io
from datetime import datetime
from functools import lru_cache


app = Flask(__name__)


# =========================================================
# PATHS
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_FILE = os.path.join(
    BASE_DIR,
    'data',
    'school_master.csv'
)


# =========================================================
# STANDARD SCHOOL STRUCTURES
# =========================================================

STANDARD_STRUCTURES = {
    (1, 5): '1–5',
    (1, 8): '1–8',
    (6, 8): '6–8',
    (1, 10): '1–10',
    (6, 10): '6–10',
    (9, 10): '9–10',
    (1, 12): '1–12',
    (6, 12): '6–12',
    (9, 12): '9–12',
    (11, 12): '11–12'
}


# =========================================================
# TEMPLATE FILTER
# =========================================================

@app.template_filter('comma')
def comma(value):

    try:
        return f'{int(float(value)):,}'

    except (ValueError, TypeError):
        return str(value)


# =========================================================
# SAFE INTEGER
# =========================================================

def safe_int(value):

    try:

        if pd.isna(value):
            return 0

        return int(float(value))

    except (ValueError, TypeError):
        return 0


# =========================================================
# RESOURCE VALUE
# =========================================================

def resource_value(value):

    if pd.isna(value):
        return 0

    if isinstance(value, str):

        v = value.strip().lower()

        if v in {
            'yes',
            'y',
            '1',
            'true',
            'available',
            'avail',
            'present'
        }:
            return 1

        if v in {
            'no',
            'n',
            '0',
            'false',
            'not available',
            'absent'
        }:
            return 0

    return safe_int(value)



# =========================================================
# LOAD DATA
# =========================================================
@lru_cache(maxsize=1)
def load_data():

    if not os.path.exists(DATA_FILE):

        raise FileNotFoundError(
            f'Data file not found: {DATA_FILE}'
        )

    df = pd.read_csv(
        DATA_FILE,
        low_memory=False
    )

    numeric = [
        'lowclass',
        'highclass',
        'total_students',
        'total_tch',
        'total_class_rooms',
        'classrooms_in_good_condition',
        'classrooms_needs_minor_repair',
        'classrooms_needs_major_repair',
        'total_boys_toilet',
        'total_girls_toilet',
        'desktop',
        'laptop',
        'tablet',
        'internet',
        'electricity_availability',
        'library_availability',
        'playground_available',
        'classroom_repair_gap'
    ]

    for c in numeric:

        if c in df.columns:

            df[c] = pd.to_numeric(
                df[c],
                errors='coerce'
            ).fillna(0)

    for c in [
        'block',
        'lgd_vill_name'
    ]:

        if c in df.columns:

            df[c] = (
                df[c]
                .fillna('')
                .astype(str)
            )

    if 'pseudocode' in df.columns:

        df['pseudocode'] = (
            df['pseudocode']
            .astype(str)
            .str.replace(
                r'\.0$',
                '',
                regex=True
            )
        )

    return df


# =========================================================
# STRUCTURE NAME
# =========================================================

def structure_name(low, high):

    key = (
        safe_int(low),
        safe_int(high)
    )

    return STANDARD_STRUCTURES.get(
        key,
        f'{key[0]}–{key[1]}'
        if key[0] and key[1]
        else 'Unknown'
    )


# =========================================================
# STRUCTURE STATUS
# =========================================================

def structure_status(low, high):

    key = (
        safe_int(low),
        safe_int(high)
    )

    return (
        'STANDARD'
        if key in STANDARD_STRUCTURES
        else 'ODD'
    )


# =========================================================
# RECOMMENDED STRUCTURE
# =========================================================

def recommended_structure(row):

    if (
        structure_status(
            row.get('lowclass'),
            row.get('highclass')
        )
        == 'STANDARD'
    ):

        return structure_name(
            row.get('lowclass'),
            row.get('highclass')
        )

    low = safe_int(
        row.get('lowclass')
    )

    high = safe_int(
        row.get('highclass')
    )

    candidates = []

    for (sl, sh), label in STANDARD_STRUCTURES.items():

        if sl <= low and sh >= high:

            candidates.append(
                (
                    (
                        sh - sl,
                        abs(sl - low) +
                        abs(sh - high)
                    ),
                    label
                )
            )

    if candidates:

        return sorted(
            candidates,
            key=lambda x: x[0]
        )[0][1]

    return '1–12'


# =========================================================
# PRIORITY CALCULATION
# =========================================================

def calculate_priority(row):

    score = 0

    reasons = []

    actions = []

    students = safe_int(
        row.get('total_students')
    )

    teachers = safe_int(
        row.get('total_tch')
    )

    rooms = safe_int(
        row.get('total_class_rooms')
    )


    # -----------------------------------------------------
    # ODD STRUCTURE
    # -----------------------------------------------------

    if (
        structure_status(
            row.get('lowclass'),
            row.get('highclass')
        )
        == 'ODD'
    ):

        score += 4

        reasons.append(
            'Non-standard grade configuration'
        )

        actions.append(
            'Review and align school grade structure with an approved configuration'
        )


    # -----------------------------------------------------
    # STUDENTS / TEACHERS
    # -----------------------------------------------------

    if students > 0 and teachers == 0:

        score += 4

        reasons.append(
            'Students recorded but no teachers recorded'
        )

        actions.append(
            'Verify teacher deployment data and staffing requirement'
        )

    elif teachers > 0:

        ratio = students / teachers

        if ratio > 40:

            score += 3

            reasons.append(
                f'High student–teacher ratio ({ratio:.1f}:1)'
            )

            actions.append(
                'Review teacher requirement / rationalisation'
            )

        elif ratio > 30:

            score += 2

            reasons.append(
                f'Elevated student–teacher ratio ({ratio:.1f}:1)'
            )

            actions.append(
                'Review staffing capacity'
            )


    # -----------------------------------------------------
    # STUDENTS / CLASSROOMS
    # -----------------------------------------------------

    if students > 0 and rooms == 0:

        score += 4

        reasons.append(
            'Students recorded but no classrooms recorded'
        )

        actions.append(
            'Validate infrastructure data and classroom requirement'
        )

    elif rooms > 0:

        per = students / rooms

        if per > 50:

            score += 3

            reasons.append(
                f'High students per classroom ({per:.1f})'
            )

            actions.append(
                'Review classroom capacity'
            )

        elif per > 40:

            score += 2

            reasons.append(
                f'Elevated students per classroom ({per:.1f})'
            )

            actions.append(
                'Review classroom capacity'
            )


    # -----------------------------------------------------
    # INTERNET
    # -----------------------------------------------------

    if resource_value(
        row.get('internet')
    ) == 0:

        score += 1

        reasons.append(
            'Internet not recorded as available'
        )

        actions.append(
            'Assess digital connectivity requirement'
        )


    # -----------------------------------------------------
    # ELECTRICITY
    # -----------------------------------------------------

    if resource_value(
        row.get('electricity_availability')
    ) == 0:

        score += 2

        reasons.append(
            'Electricity not recorded as available'
        )

        actions.append(
            'Assess electricity infrastructure'
        )


    # -----------------------------------------------------
    # LIBRARY
    # -----------------------------------------------------

    if resource_value(
        row.get('library_availability')
    ) == 0:

        score += 1

        reasons.append(
            'Library not recorded as available'
        )

        actions.append(
            'Assess library/resource-centre requirement'
        )


    # -----------------------------------------------------
    # PLAYGROUND
    # -----------------------------------------------------

    if resource_value(
        row.get('playground_available')
    ) == 0:

        score += 1

        reasons.append(
            'Playground not recorded as available'
        )

        actions.append(
            'Assess play-area requirement'
        )


    # -----------------------------------------------------
    # PRIORITY
    # -----------------------------------------------------

    if score >= 8:

        priority = 'HIGH'

    elif score >= 4:

        priority = 'MEDIUM'

    else:

        priority = 'LOW'


    return {

        'score': score,

        'priority': priority,

        'reasons': reasons,

        'actions': actions,

        'student_teacher_ratio':
            round(
                students / teachers,
                2
            )
            if teachers
            else None,

        'students_per_classroom':
            round(
                students / rooms,
                2
            )
            if rooms
            else None
    }


# =========================================================
# ROW TO SCHOOL
# =========================================================

def row_to_school(row):

    d = (
        row.to_dict()
        if hasattr(row, 'to_dict')
        else dict(row)
    )

    for k, v in list(d.items()):

        if pd.isna(v):

            d[k] = None

        elif hasattr(v, 'item'):

            try:

                d[k] = v.item()

            except Exception:

                pass


    d['pseudocode'] = str(
        d.get('pseudocode', '')
    )


    d['current_structure'] = structure_name(
        d.get('lowclass'),
        d.get('highclass')
    )


    d['structure_status'] = structure_status(
        d.get('lowclass'),
        d.get('highclass')
    )


    d['recommended_structure'] = (
        recommended_structure(d)
    )


    d['priority'] = calculate_priority(d)


    d['resource_data'] = {

        'internet':
            bool(
                resource_value(
                    d.get('internet')
                )
            ),

        'electricity':
            bool(
                resource_value(
                    d.get(
                        'electricity_availability'
                    )
                )
            ),

        'library':
            bool(
                resource_value(
                    d.get(
                        'library_availability'
                    )
                )
            ),

        'playground':
            bool(
                resource_value(
                    d.get(
                        'playground_available'
                    )
                )
            )
    }


    return d


# =========================================================
# BUILD DASHBOARD
# =========================================================

def build_dashboard(df):

    total = len(df)


    odd = int(
        (
            df.apply(
                lambda r:
                structure_status(
                    r['lowclass'],
                    r['highclass']
                ),
                axis=1
            )
            == 'ODD'
        ).sum()
    )


    standard = total - odd


    students = int(
        df['total_students'].sum()
    )


    teachers = int(
        df['total_tch'].sum()
    )


    classrooms = int(
        df['total_class_rooms'].sum()
    )


    blocks = sorted(
        [
            str(x)
            for x in df['block']
            .dropna()
            .unique()
            if str(x).strip()
        ]
    )


    # -----------------------------------------------------
    # STRUCTURE COUNTS
    # -----------------------------------------------------

    structure_counts = {}


    for _, r in df.iterrows():

        n = structure_name(
            r['lowclass'],
            r['highclass']
        )

        structure_counts[n] = (
            structure_counts.get(n, 0) + 1
        )


    # -----------------------------------------------------
    # BLOCK ANALYSIS
    # -----------------------------------------------------

    block_rows = []


    for block, g in df.groupby(
        'block',
        dropna=False
    ):

        name = (
            str(block)
            if not pd.isna(block)
            and str(block).strip()
            else 'Unknown'
        )


        scores = [

            calculate_priority(r)['score']

            for _, r in g.iterrows()

        ]


        odd_count = sum(

            structure_status(
                r['lowclass'],
                r['highclass']
            )
            == 'ODD'

            for _, r in g.iterrows()

        )


        avg = (
            round(
                sum(scores) / len(scores),
                2
            )
            if scores
            else 0
        )


        if avg >= 5:

            priority = 'HIGH'

        elif avg >= 2.5:

            priority = 'MEDIUM'

        else:

            priority = 'LOW'


        block_rows.append({

            'block': name,

            'schools': len(g),

            'odd_schools':
                int(odd_count),

            'students':
                int(
                    g['total_students'].sum()
                ),

            'teachers':
                int(
                    g['total_tch'].sum()
                ),

            'classrooms':
                int(
                    g['total_class_rooms'].sum()
                ),

            'avg_priority_score':
                avg,

            'priority':
                priority

        })


    block_rows.sort(
        key=lambda x: (
            -x['avg_priority_score'],
            x['block']
        )
    )


    # -----------------------------------------------------
    # ODD SCHOOLS
    # -----------------------------------------------------

    odd_schools = []


    for _, r in df.iterrows():

        if (
            structure_status(
                r['lowclass'],
                r['highclass']
            )
            == 'ODD'
        ):

            s = row_to_school(r)


            odd_schools.append({

                'pseudocode':
                    s['pseudocode'],

                'block':
                    s.get('block'),

                'village':
                    s.get('lgd_vill_name'),

                'current_structure':
                    s['current_structure'],

                'recommended_structure':
                    s['recommended_structure'],

                'priority':
                    s['priority']['priority'],

                'score':
                    s['priority']['score'],

                'total_students':
                    safe_int(
                        s.get(
                            'total_students'
                        )
                    ),

                'total_tch':
                    safe_int(
                        s.get(
                            'total_tch'
                        )
                    )
            })


    return {

        'total': total,

        'standard': standard,

        'odd': odd,

        'students': students,

        'teachers': teachers,

        'classrooms': classrooms,

        'blocks': blocks,

        'structure_counts':
            structure_counts,

        'block_rows':
            block_rows,

        'odd_schools':
            odd_schools
    }


# =========================================================
# FILTER DATA
# =========================================================

def filtered_df(df):

    block = request.args.get(
        'block',
        ''
    ).strip()


    status = request.args.get(
        'status',
        'ALL'
    ).strip().upper()


    q = request.args.get(
        'q',
        ''
    ).strip()


    out = df.copy()


    # -----------------------------------------------------
    # BLOCK FILTER
    # -----------------------------------------------------

    if block:

        out = out[
            out['block']
            .astype(str)
            .str.upper()
            == block.upper()
        ]


    # -----------------------------------------------------
    # STATUS FILTER
    # -----------------------------------------------------

    if status in {
        'STANDARD',
        'ODD'
    }:

        out = out[
            out.apply(
                lambda r:
                structure_status(
                    r['lowclass'],
                    r['highclass']
                )
                == status,
                axis=1
            )
        ]


    # -----------------------------------------------------
    # SEARCH FILTER
    # -----------------------------------------------------

    if q:

        qu = q.upper()


        out = out[
            out['pseudocode']
            .astype(str)
            .str.upper()
            .str.contains(
                qu,
                na=False
            )

            |

            out['lgd_vill_name']
            .astype(str)
            .str.upper()
            .str.contains(
                qu,
                na=False
            )

            |

            out['block']
            .astype(str)
            .str.upper()
            .str.contains(
                qu,
                na=False
            )
        ]


    return out


# =========================================================
# HOME PAGE
# =========================================================

@app.route('/')
def index():

    df = load_data()

    filtered = filtered_df(df)

    dashboard = build_dashboard(
        filtered
    )


    # IMPORTANT:
    # Schools are NOT loaded here.
    # They will be loaded through /api/schools
    # in small batches.

    schools = []


    return render_template(
        'index.html',

        dashboard=dashboard,

        schools=schools,

        filters={

            'block':
                request.args.get(
                    'block',
                    ''
                ).strip(),

            'status':
                request.args.get(
                    'status',
                    'ALL'
                ).strip().upper(),

            'q':
                request.args.get(
                    'q',
                    ''
                ).strip()
        }
    )


# =========================================================
# SCHOOL DETAIL
# =========================================================

@app.route('/school/<pseudocode>')
def school_detail(pseudocode):

    df = load_data()


    match = df[
        df['pseudocode']
        .astype(str)
        == str(pseudocode)
    ]


    if match.empty:

        abort(404)


    return render_template(
        'school_detail.html',
        school=row_to_school(
            match.iloc[0]
        )
    )


# =========================================================
# SCHOOL API - BATCH LOADING
# =========================================================

@app.route('/api/schools')
def api_schools():

    df = load_data()


    # Apply current block/status/search filters
    out = filtered_df(df)


    # -----------------------------------------------------
    # BATCH SIZE
    # -----------------------------------------------------

    limit = min(

        max(

            safe_int(
                request.args.get(
                    'limit',
                    50
                )
            ),

            1

        ),

        100

    )


    # -----------------------------------------------------
    # OFFSET
    # -----------------------------------------------------

    offset = max(

        safe_int(
            request.args.get(
                'offset',
                0
            )
        ),

        0

    )


    # -----------------------------------------------------
    # TOTAL FILTERED SCHOOLS
    # -----------------------------------------------------

    total = len(out)


    # -----------------------------------------------------
    # GET ONLY CURRENT BATCH
    # -----------------------------------------------------

    batch = out.iloc[
        offset:
        offset + limit
    ]


    records = []


    # -----------------------------------------------------
    # CONVERT BATCH TO JSON
    # -----------------------------------------------------

    for _, r in batch.iterrows():

        s = row_to_school(r)


        records.append({

            'pseudocode':
                s['pseudocode'],

            'block':
                s.get('block'),

            'village':
                s.get(
                    'lgd_vill_name'
                ),

            'structure':
                s['current_structure'],

            'status':
                s['structure_status'],

            'students':
                safe_int(
                    s.get(
                        'total_students'
                    )
                ),

            'teachers':
                safe_int(
                    s.get(
                        'total_tch'
                    )
                ),

            'priority':
                s['priority']['priority'],

            'score':
                s['priority']['score']

        })


    # -----------------------------------------------------
    # JSON RESPONSE
    # -----------------------------------------------------

    return jsonify({

        'count':
            total,

        'offset':
            offset,

        'limit':
            limit,

        'has_more':
            offset + len(records) < total,

        'results':
            records

    })


# =========================================================
# CSV DOWNLOAD HELPER
# =========================================================

def csv_download(
    df,
    filename
):

    buffer = io.StringIO()


    df.to_csv(
        buffer,
        index=False
    )


    buffer.seek(0)


    return send_file(

        io.BytesIO(
            buffer
            .getvalue()
            .encode(
                'utf-8-sig'
            )
        ),

        mimetype='text/csv',

        as_attachment=True,

        download_name=filename
    )


# =========================================================
# SCHOOL REPORT DOWNLOAD
# =========================================================

@app.route('/download/report')
def download_report():

    df = load_data()

    out = df.copy()


    out['structure_name'] = out.apply(

        lambda r:
        structure_name(
            r['lowclass'],
            r['highclass']
        ),

        axis=1
    )


    out['structure_status'] = out.apply(

        lambda r:
        structure_status(
            r['lowclass'],
            r['highclass']
        ),

        axis=1
    )


    out['recommended_structure'] = out.apply(

        recommended_structure,

        axis=1
    )


    p = out.apply(

        calculate_priority,

        axis=1,

        result_type='expand'
    )


    out['priority_score'] = p['score']

    out['priority'] = p['priority']


    return csv_download(

        out,

        'EduStruct_AI_School_Report.csv'
    )


# =========================================================
# BLOCK REPORT DOWNLOAD
# =========================================================

@app.route('/download/block-report')
def download_block_report():

    dashboard = build_dashboard(
        load_data()
    )


    return csv_download(

        pd.DataFrame(
            dashboard['block_rows']
        ),

        'EduStruct_AI_Block_Resource_Report.csv'
    )


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route('/health')
def health():

    try:

        return jsonify({

            'status':
                'ok',

            'schools':
                len(
                    load_data()
                ),

            'timestamp':
                datetime.utcnow()
                .isoformat()
                + 'Z'

        })


    except Exception as e:

        return jsonify({

            'status':
                'error',

            'message':
                str(e)

        }), 500


# =========================================================
# 404 ERROR
# =========================================================

@app.errorhandler(404)
def not_found(_):

    return render_template(
        '404.html'
    ), 404


# =========================================================
# RUN APP
# =========================================================

if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )