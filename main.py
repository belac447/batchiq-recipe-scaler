from flask import Flask, request, jsonify, render_template_string
import json
import re
import os
from supabase import create_client

app = Flask(__name__)

# Initialize Supabase client
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Load protein lookup and aliases
to_grams = {'g':1,'kg':1000,'oz':28.35,'cup':240,'tbsp':15,'tsp':5}
with open('protein_lookup.json') as f:
    protein_100g = json.load(f)
try:
    with open('aliases.json') as f:
        aliases = json.load(f)
except:
    aliases = {}

# Fancy Bootstrap-based template
template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
    <title>BatchIQ Recipe Scaler</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f8f9fa; }
        .card-main { margin-top: 2rem; }
        .result-card { margin-top: 1rem; }
        .noscale { font-style: italic; color: #6c757d; }
        .lookup { font-size: 0.9rem; color: #198754; }
    </style>
</head>
<body>
<div class="container">
    <div class="card card-main shadow-sm">
        <div class="card-body">
            <h1 class="card-title text-center">BatchIQ Recipe Scaler</h1>
            <form id="scale-form" method="post" action="/scale" class="row g-3">
                <div class="col-md-4">
                    <label for="servings" class="form-label">Current Servings</label>
                    <input type="number" class="form-control" id="servings" name="servings" required>
                </div>
                <div class="col-md-4">
                    <label for="scaling_type" class="form-label">Scaling Method</label>
                    <select class="form-select" id="scaling_type" name="scaling_type" onchange="toggleFields()">
                        <option value="servings">Scale by Servings</option>
                        <option value="protein_target">Target Protein per Serving</option>
                    </select>
                </div>
                <div class="col-md-4" id="mode_servings_container">
                    <label for="target_servings" class="form-label">Target Servings</label>
                    <input type="number" class="form-control" id="target_servings" name="target_servings">
                </div>
                <div class="col-md-4" id="mode_protein_container" style="display:none;">
                    <label for="target_protein" class="form-label">Target Protein (g)</label>
                    <input type="number" step="0.1" class="form-control" id="target_protein" name="target_protein">
                </div>
                <div class="col-12">
                    <label for="ingredients" class="form-label">Ingredients (one per line)</label>
                    <textarea class="form-control" id="ingredients" name="ingredients" rows="5" placeholder="e.g. 1/2 cup oats, 5g protein" required></textarea>
                </div>
                <div class="col-12 text-center">
                    <button type="submit" class="btn btn-primary">Scale Recipe</button>
                </div>
            </form>
        </div>
    </div>

    {% if warnings %}
    <div class="alert alert-warning mt-4" role="alert">
        <ul class="mb-0">
        {% for w in warnings %}
            <li>{{ w }}</li>
        {% endfor %}
        </ul>
    </div>
    {% endif %}

    {% if scaled %}
    <div class="card result-card shadow-sm">
        <div class="card-body">
            <h2 class="card-title">Scaled Ingredients</h2>
            <ul class="list-group list-group-flush">
            {% for item in scaled %}
                {% if item.no_scale %}
                <li class="list-group-item noscale">{{ item.name }}: not scaled (adjust to taste)</li>
                {% else %}
                <li class="list-group-item">
                    <strong>{{ item.quantity }} {{ item.unit }}</strong> {{ item.name }}
                    {% if item.protein is not none %}<span class="lookup">( {{ item.protein }}g protein )</span>{% endif %}
                </li>
                {% endif %}
            {% endfor %}
            </ul>
            <p class="mt-3"><strong>Scale Factor:</strong> {{ factor }}</p>
            {% if scaling_type == 'servings' %}
            <p><strong>Approx. protein per serving:</strong> {{ approx_pps }}g</p>
            {% else %}
            <p><strong>New protein per serving (for {{ servings }} servings):</strong> {{ new_pps }}g</p>
            {% endif %}
        </div>
    </div>
    {% endif %}
</div>

<script>
function toggleFields() {
    const mode = document.getElementById('scaling_type').value;
    document.getElementById('mode_servings_container').style.display = mode === 'servings' ? 'block' : 'none';
    document.getElementById('mode_protein_container').style.display = mode === 'protein_target' ? 'block' : 'none';
}
</script>
</body>
</html>
"""

# Parser and API logic remain unchanged

def parse_line(line):
    text = line.strip().lstrip('-* ').strip()
    qty_pattern = r'(?P<q>\d+\s+\d+/\d+|\d+/\d+|\d+\.?\d*)'
    regex = rf'^{qty_pattern}\s*(?P<u>[a-zA-Z]+)\s*(?P<n>.*)'
    m = re.match(regex, text)
    if not m:
        return {'name': text, 'no_scale': True, 'protein': None}
    qty_str = m.group('q')
    if '/' in qty_str:
        if ' ' in qty_str:
            whole, frac = qty_str.split(' ')
            num, den = frac.split('/')
            qty = float(whole) + float(num)/float(den)
        else:
            num, den = qty_str.split('/')
            qty = float(num)/float(den)
    else:
        qty = float(qty_str)
    unit = m.group('u').lower()
    name = m.group('n').strip().lower()
    # Strip parentheses
    name = re.sub(r'\s*\(.*?\)', '', name).strip()
    # Alias mapping
    for alias, actual in aliases.items():
        if alias in name:
            name = actual
            break
    pm = re.search(r'(?P<p>\d+\.?\d*)\s*g\s*protein', text, re.IGNORECASE)
    if pm:
        protein = float(pm.group('p'))
    else:
        protein = None
        matches = [(k, v) for k, v in protein_100g.items() if k in name and unit in to_grams]
        if matches:
            best_key, best_val = max(matches, key=lambda x: len(x[0]))
            grams = qty * to_grams[unit]
            protein = round(grams/100*best_val, 1)
    return {'name': name, 'quantity': qty, 'unit': unit, 'protein': protein, 'no_scale': False}

@app.route('/', methods=['GET'])
def index():
    return render_template_string(template)

@app.route('/scale', methods=['POST'])
def scale():
    stype = request.form.get('scaling_type')
    servings = float(request.form.get('servings') or 1)
    lines = request.form.get('ingredients', '').splitlines()
    ingredients = [parse_line(l) for l in lines if l.strip()]
    warnings = []

    total_protein = sum(i['protein'] for i in ingredients if i['protein'] is not None)
    factor = 1.0
    new_pps = None
    approx_pps = None

    if stype == 'servings':
        try:
            target_servings = float(request.form.get('target_servings') or 0)
            factor = target_servings / servings
        except:
            warnings.append('Invalid target servings')
    else:
        try:
            tp = float(request.form.get('target_protein') or 0)
            if total_protein <= 0:
                warnings.append('No protein data to scale')
            else:
                factor = (tp * servings) / total_protein
                new_pps = tp
        except:
            warnings.append('Invalid target protein')

    scaled = []
    for ing in ingredients:
        if ing['no_scale']:
            scaled.append({'name': ing['name'], 'no_scale': True, 'protein': None})
        else:
            qty = round(ing['quantity'] * factor, 1)
            prot = round(ing['protein'] * factor, 1) if ing['protein'] is not None else None
            scaled.append({'name': ing['name'], 'quantity': qty, 'unit': ing['unit'], 'protein': prot, 'no_scale': False})

    if stype == 'servings' and target_servings:
        total_scaled_protein = sum(item['protein'] for item in scaled if item['protein'] is not None)
        approx_pps = round(total_scaled_protein / target_servings, 1)

    return render_template_string(
        template,
        scaled=scaled,
        factor=round(factor, 1),
        warnings=warnings,
        scaling_type=stype,
        servings=servings,
        new_pps=new_pps,
        approx_pps=approx_pps
    )

@app.route('/scale-recipe', methods=['POST'])
def scale_recipe_api():
    data = request.get_json() or {}
    email = data.get('email')
    if not email:
        return jsonify({"error":"Email required"}), 400
    # Fetch user record
    resp = supabase.from_('users').select('usage_count,paid').eq('email', email).single().execute()
    user = resp.data
    if not user:
        return jsonify({"error":"Email not registered"}), 400
    if not user['paid'] and user['usage_count'] >= 5:
        return jsonify({
            "error": "limit_reached",
            "message": "You’ve used your 5 free scalings. Please upgrade to continue."
        }), 402
    # Parse ingredients
    if isinstance(data.get('ingredients'), list):
        ingredients = data['ingredients']
    else:
        ingredients = [parse_line(l) for l in data.get('ingredients','').splitlines() if l.strip()]
    total_protein = sum(i['protein'] for i in ingredients if i.get('protein') is not None)
    serv = data.get('servings', 1)
    factor = 1.0
    result_pps = None
    if data.get('scaling_type') == 'servings':
        ts = data.get('target_servings') or 0
        if serv and ts:
            factor = ts/serv
    else:
        tp = data.get('target_protein') or 0
        if total_protein > 0 and tp:
            factor = (tp * serv)/total_protein
            result_pps = tp
    scaled_resp = []
    for ing in ingredients:
        if ing.get('no_scale'):
            scaled_resp.append({'name': ing['name'], 'no_scale': True})
        else:
            qty = round(ing['quantity']*factor,1)
            prot = round(ing.get('protein',0)*factor,1) if ing.get('protein') is not None else None
            scaled_resp.append({'name': ing['name'], 'quantity': qty, 'unit': ing['unit'], 'protein': prot})
    # Increment usage
    supabase.from_('users').update({'usage_count': user['usage_count']+1}).eq('email', email).execute()
    resp_payload = {'scaling_type': data.get('scaling_type'), 'factor': round(factor,1), 'scaled_ingredients': scaled_resp}
    if result_pps is not None:
        resp_payload['new_pps'] = result_pps
    return jsonify(resp_payload)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
