from flask import Flask, render_template, request, jsonify, send_file, abort
import pandas as pd
import os, io
from datetime import datetime

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'data', 'school_master.csv')

STANDARD_STRUCTURES = {
    (1,5): '1–5', (1,8): '1–8', (6,8): '6–8', (1,10): '1–10',
    (6,10): '6–10', (9,10): '9–10', (1,12): '1–12', (6,12): '6–12',
    (9,12): '9–12', (11,12): '11–12'
}

@app.template_filter('comma')
def comma(value):
    try: return f'{int(float(value)):,}'
    except (ValueError, TypeError): return str(value)

def safe_int(value):
    try:
        if pd.isna(value): return 0
        return int(float(value))
    except (ValueError, TypeError): return 0

def resource_value(value):
    if pd.isna(value): return 0
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {'yes','y','1','true','available','avail','present'}: return 1
        if v in {'no','n','0','false','not available','absent'}: return 0
    return safe_int(value)

def load_data():
    if not os.path.exists(DATA_FILE):
        raise FileNotFoundError(f'Data file not found: {DATA_FILE}')
    df = pd.read_csv(DATA_FILE, low_memory=False)
    numeric = ['lowclass','highclass','total_students','total_tch','total_class_rooms',
               'classrooms_in_good_condition','classrooms_needs_minor_repair',
               'classrooms_needs_major_repair','total_boys_toilet','total_girls_toilet',
               'desktop','laptop','tablet','internet','electricity_availability',
               'library_availability','playground_available','classroom_repair_gap']
    for c in numeric:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    for c in ['block','lgd_vill_name']:
        if c in df.columns: df[c] = df[c].fillna('').astype(str)
    df['pseudocode'] = df['pseudocode'].astype(str).str.replace(r'\.0$','',regex=True)
    return df

def structure_name(low, high):
    key=(safe_int(low),safe_int(high))
    return STANDARD_STRUCTURES.get(key, f'{key[0]}–{key[1]}' if key[0] and key[1] else 'Unknown')

def structure_status(low, high):
    return 'STANDARD' if (safe_int(low),safe_int(high)) in STANDARD_STRUCTURES else 'ODD'

def recommended_structure(row):
    if structure_status(row.get('lowclass'), row.get('highclass')) == 'STANDARD':
        return structure_name(row.get('lowclass'), row.get('highclass'))
    low, high = safe_int(row.get('lowclass')), safe_int(row.get('highclass'))
    candidates=[]
    for (sl,sh),label in STANDARD_STRUCTURES.items():
        if sl <= low and sh >= high:
            candidates.append(((sh-sl,abs(sl-low)+abs(sh-high)),label))
    return sorted(candidates,key=lambda x:x[0])[0][1] if candidates else '1–12'

def calculate_priority(row):
    score=0; reasons=[]; actions=[]
    students=safe_int(row.get('total_students')); teachers=safe_int(row.get('total_tch')); rooms=safe_int(row.get('total_class_rooms'))
    if structure_status(row.get('lowclass'),row.get('highclass'))=='ODD':
        score+=4; reasons.append('Non-standard grade configuration'); actions.append('Review and align school grade structure with an approved configuration')
    if students>0 and teachers==0:
        score+=4; reasons.append('Students recorded but no teachers recorded'); actions.append('Verify teacher deployment data and staffing requirement')
    if teachers>0:
        ratio=students/teachers
        if ratio>40: score+=3; reasons.append(f'High student–teacher ratio ({ratio:.1f}:1)'); actions.append('Review teacher requirement / rationalisation')
        elif ratio>30: score+=2; reasons.append(f'Elevated student–teacher ratio ({ratio:.1f}:1)'); actions.append('Review staffing capacity')
    if students>0 and rooms==0:
        score+=4; reasons.append('Students recorded but no classrooms recorded'); actions.append('Validate infrastructure data and classroom requirement')
    elif rooms>0:
        per=students/rooms
        if per>50: score+=3; reasons.append(f'High students per classroom ({per:.1f})'); actions.append('Review classroom capacity')
        elif per>40: score+=2; reasons.append(f'Elevated students per classroom ({per:.1f})'); actions.append('Review classroom capacity')
    if resource_value(row.get('internet'))==0: score+=1; reasons.append('Internet not recorded as available'); actions.append('Assess digital connectivity requirement')
    if resource_value(row.get('electricity_availability'))==0: score+=2; reasons.append('Electricity not recorded as available'); actions.append('Assess electricity infrastructure')
    if resource_value(row.get('library_availability'))==0: score+=1; reasons.append('Library not recorded as available'); actions.append('Assess library/resource-centre requirement')
    if resource_value(row.get('playground_available'))==0: score+=1; reasons.append('Playground not recorded as available'); actions.append('Assess play-area requirement')
    priority='HIGH' if score>=8 else 'MEDIUM' if score>=4 else 'LOW'
    return {'score':score,'priority':priority,'reasons':reasons,'actions':actions,
            'student_teacher_ratio':round(students/teachers,2) if teachers else None,
            'students_per_classroom':round(students/rooms,2) if rooms else None}

def row_to_school(row):
    d=row.to_dict() if hasattr(row,'to_dict') else dict(row)
    for k,v in list(d.items()):
        if pd.isna(v): d[k]=None
        elif hasattr(v,'item'):
            try: d[k]=v.item()
            except Exception: pass
    d['pseudocode']=str(d.get('pseudocode',''))
    d['current_structure']=structure_name(d.get('lowclass'),d.get('highclass'))
    d['structure_status']=structure_status(d.get('lowclass'),d.get('highclass'))
    d['recommended_structure']=recommended_structure(d)
    d['priority']=calculate_priority(d)
    d['resource_data']={
        'internet':bool(resource_value(d.get('internet'))),
        'electricity':bool(resource_value(d.get('electricity_availability'))),
        'library':bool(resource_value(d.get('library_availability'))),
        'playground':bool(resource_value(d.get('playground_available')))
    }
    return d

def build_dashboard(df):
    total=len(df)
    odd=int((df.apply(lambda r: structure_status(r['lowclass'],r['highclass']),axis=1)=='ODD').sum())
    standard=total-odd
    students=int(df['total_students'].sum()); teachers=int(df['total_tch'].sum()); classrooms=int(df['total_class_rooms'].sum())
    blocks=sorted([str(x) for x in df['block'].dropna().unique() if str(x).strip()])
    structure_counts={}
    for _,r in df.iterrows():
        n=structure_name(r['lowclass'],r['highclass']); structure_counts[n]=structure_counts.get(n,0)+1
    block_rows=[]
    for block,g in df.groupby('block',dropna=False):
        name=str(block) if not pd.isna(block) and str(block).strip() else 'Unknown'
        scores=[calculate_priority(r)['score'] for _,r in g.iterrows()]
        odd_count=sum(structure_status(r['lowclass'],r['highclass'])=='ODD' for _,r in g.iterrows())
        avg=round(sum(scores)/len(scores),2) if scores else 0
        priority='HIGH' if avg>=5 else 'MEDIUM' if avg>=2.5 else 'LOW'
        block_rows.append({'block':name,'schools':len(g),'odd_schools':int(odd_count),'students':int(g['total_students'].sum()),
                           'teachers':int(g['total_tch'].sum()),'classrooms':int(g['total_class_rooms'].sum()),
                           'avg_priority_score':avg,'priority':priority})
    block_rows.sort(key=lambda x:(-x['avg_priority_score'],x['block']))
    odd_schools=[]
    for _,r in df.iterrows():
        if structure_status(r['lowclass'],r['highclass'])=='ODD':
            s=row_to_school(r)
            odd_schools.append({'pseudocode':s['pseudocode'],'block':s.get('block'),'village':s.get('lgd_vill_name'),
                'current_structure':s['current_structure'],'recommended_structure':s['recommended_structure'],
                'priority':s['priority']['priority'],'score':s['priority']['score'],
                'total_students':safe_int(s.get('total_students')),'total_tch':safe_int(s.get('total_tch'))})
    return {'total':total,'standard':standard,'odd':odd,'students':students,'teachers':teachers,'classrooms':classrooms,
            'blocks':blocks,'structure_counts':structure_counts,'block_rows':block_rows,'odd_schools':odd_schools}

def filtered_df(df):
    block=request.args.get('block','').strip(); status=request.args.get('status','ALL').strip().upper(); q=request.args.get('q','').strip()
    out=df.copy()
    if block: out=out[out['block'].astype(str).str.upper()==block.upper()]
    if status in {'STANDARD','ODD'}: out=out[out.apply(lambda r:structure_status(r['lowclass'],r['highclass'])==status,axis=1)]
    if q:
        qu=q.upper()
        out=out[out['pseudocode'].astype(str).str.upper().str.contains(qu,na=False)|out['lgd_vill_name'].astype(str).str.upper().str.contains(qu,na=False)|out['block'].astype(str).str.upper().str.contains(qu,na=False)]
    return out

@app.route('/')
def index():
    df=load_data(); filtered=filtered_df(df); dashboard=build_dashboard(filtered)
    #schools=[row_to_school(r) for _,r in filtered.iterrows()]
    schools=[]
    return render_template('index.html',dashboard=dashboard,schools=schools,filters={'block':request.args.get('block','').strip(),'status':request.args.get('status','ALL').strip().upper(),'q':request.args.get('q','').strip()})

@app.route('/school/<pseudocode>')
def school_detail(pseudocode):
    df=load_data(); match=df[df['pseudocode'].astype(str)==str(pseudocode)]
    if match.empty: abort(404)
    return render_template('school_detail.html',school=row_to_school(match.iloc[0]))

@app.route('/api/schools')
def api_schools():
    df=load_data(); out=filtered_df(df); limit=min(max(safe_int(request.args.get('limit',100)),1),500)
    records=[]
    for _,r in out.head(limit).iterrows():
        s=row_to_school(r); records.append({'pseudocode':s['pseudocode'],'block':s.get('block'),'village':s.get('lgd_vill_name'),
            'structure':s['current_structure'],'status':s['structure_status'],'students':safe_int(s.get('total_students')),
            'teachers':safe_int(s.get('total_tch')),'priority':s['priority']['priority'],'score':s['priority']['score']})
    return jsonify({'count':len(out),'results':records})

def csv_download(df,filename):
    buffer=io.StringIO(); df.to_csv(buffer,index=False); buffer.seek(0)
    return send_file(io.BytesIO(buffer.getvalue().encode('utf-8-sig')),mimetype='text/csv',as_attachment=True,download_name=filename)

@app.route('/download/report')
def download_report():
    df=load_data(); out=df.copy(); out['structure_name']=out.apply(lambda r:structure_name(r['lowclass'],r['highclass']),axis=1)
    out['structure_status']=out.apply(lambda r:structure_status(r['lowclass'],r['highclass']),axis=1); out['recommended_structure']=out.apply(recommended_structure,axis=1)
    p=out.apply(calculate_priority,axis=1,result_type='expand'); out['priority_score']=p['score']; out['priority']=p['priority']
    return csv_download(out,'EduStruct_AI_School_Report.csv')

@app.route('/download/block-report')
def download_block_report(): return csv_download(pd.DataFrame(build_dashboard(load_data())['block_rows']),'EduStruct_AI_Block_Resource_Report.csv')

@app.route('/health')
def health():
    try: return jsonify({'status':'ok','schools':len(load_data()),'timestamp':datetime.utcnow().isoformat()+'Z'})
    except Exception as e: return jsonify({'status':'error','message':str(e)}),500

@app.errorhandler(404)
def not_found(_): return render_template('404.html'),404

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=True)
