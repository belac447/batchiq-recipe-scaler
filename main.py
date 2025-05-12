from flask import Flask, request, jsonify, render_template_string
import json
import re

app = Flask(__name__)

# HTML template with approximate protein per serving for servings mode
template = """
<!DOCTYPE html>
<html>
<head>
    <title>BatchIQ Recipe Scaler</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 1rem; }
        label { font-weight: bold; margin-top: 1rem; display: block; }
        textarea { width: 100%; padding: 0.5rem; margin-bottom: 1rem; }
        input[type=number], select { width: 100%; padding: 0.5rem; margin-bottom: 1rem; }
        input[type=submit] { padding: 0.75rem 1.5rem; font-size: 1rem; }
        .noscale { color: #555; font-style: italic; }
        .lookup { color: green; margin-left: 0.5rem; }
        .note { font-size: 0.9rem; color: #666; margin-top: 1rem; }
    </style>
</head>
<body>
    <h2>BatchIQ Recipe Scaler</h2>
    <form method="post" action="/scale">
        <label>Current Servings:</label>
        <input type="number" name="servings" required>

        <label>Scaling Method:</label>
        <select name="scaling_type" id="scaling_type" onchange="toggleFields()">
            <option value="servings">Scale by Servings</option>
            <option value="protein_target">Target Protein per Serving</option>
        </select>

        <div id="mode_servings">
            <label>Target Servings:</label>
            <input type="number" name="target_servings">
        </div>

        <div id="mode_protein" style="display:none">
            <label>Target Protein per Serving (g):</label>
            <input type="number" step="0.1" name="target_protein">
        </div>

        <label>Ingredients (one per line):</label>
        <textarea name="ingredients" rows="6" required placeholder="e.g. 1/2 cup oats, 5g protein"></textarea>

        <input type="submit" value="Scale Recipe">
    </form>

    {% if warnings %}
    <h3>Warnings:</h3>
    <ul>
        {% for w in warnings %}<li class="noscale">{{ w }}</li>{% endfor %}
    </ul>
    {% endif %}

    {% if scaled %}
    <h3>Scaled Ingredients:</h3>
    <ul>
        {% for item in scaled %}
            {% if item.no_scale %}
                <li class="noscale">{{ item.name }}: not scaled (adjust to taste)</li>
            {% else %}
                <li>{{ item.quantity }} {{ item.unit }} {{ item.name }}{% if item.protein is not none %}<span class="lookup">({{ item.protein }}g protein)</span>{% endif %}</li>
            {% endif %}
        {% endfor %}
    </ul>
    <p><strong>Scale Factor:</strong> {{ factor }}</p>
    {% if scaling_type == 'servings' %}
    <p><strong>Approx. protein per serving:</strong> {{ approx_pps }} grams</p>
    {% endif %}
    {% if scaling_type == 'protein_target' %}
    <p><strong>New protein per serving (for {{ servings }} servings):</strong> {{ new_pps }} grams</p>
    {% endif %}
    <p class="note">Quantities rounded to one decimal place for readability.</p>
    {% endif %}

    <script>
    function toggleFields() {
        var mode = document.getElementById('scaling_type').value;
        document.getElementById('mode_servings').style.display = (mode === 'servings') ? 'block' : 'none';
        document.getElementById('mode_protein').style.display = (mode === 'protein_target') ? 'block' : 'none';
    }
    </script>
</body>
</html>
"""

# Load protein lookup and aliases
to_grams = {'g':1,'kg':1000,'oz':28.35,'cup':240,'tbsp':15,'tsp':5}
with open('protein_lookup.json') as f:
    protein_100g = json.load(f)
try:
    with open('aliases.json') as f:
        aliases = json.load(f)
except:
    aliases = {}


def parse_line(line):
    text = line.strip().lstrip('-* ').strip()
    # Match quantity (fractions or decimals) and unit
    qty_pattern = r'(?P<q>\d+\s+\d+/\d+|\d+/\d+|\d+\.?\d*)'
    regex = rf'^{qty_pattern}\s*(?P<u>[a-zA-Z]+)\s*(?P<n>.*)'
    m = re.match(regex, text)
    if not m:
        return {'name': text, 'no_scale': True, 'protein': None}
    # Quantity parsing\    
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
    # Remove parenthetical descriptions\    
    name = re.sub(r'\s*\(.*?\)', '', name).strip()
    # Apply aliases
    for alias, actual in aliases.items():
        if alias in name:
            name = actual
            break
    # Explicit protein override
    pm = re.search(r'(?P<p>\d+\.?\d*)\s*g\s*protein', text, re.IGNORECASE)
    if pm:
        protein = float(pm.group('p'))
    else:
        protein = None
        matches = [(k,v) for k,v in protein_100g.items() if k in name and unit in to_grams]
        if matches:
            best_key, best_val = max(matches, key=lambda x: len(x[0]))
            grams = qty * to_grams[unit]
            protein = round(grams/100 * best_val, 1)
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

    # Compute approximate protein per serving for servings mode
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
    stype = data.get('scaling_type', 'servings')
    servings = data.get('servings', 1)
    inp = data.get('ingredients', [])  
    if isinstance(inp, list):
        ingredients = [{'name':i['name'],'quantity':i['quantity'],'unit':i['unit'],'protein':i.get('protein'),'no_scale':False} for i in inp]
    else:
        ingredients = [parse_line(l) for l in inp.splitlines() if l.strip()]

    total_protein = sum(i['protein'] for i in ingredients if i['protein'] is not None)
    factor = 1.0
    result_pps = None

    if stype=='servings':
        ts = data.get('target_servings') or 0
        if servings and ts:
            factor = ts/servings
    else:
        tp = data.get('target_protein') or 0
        if total_protein>0 and tp:
            factor=(tp*servings)/total_protein
            result_pps=tp

    scaled = []
    for ing in ingredients:
        if ing.get('no_scale'):
            scaled.append({'name':ing['name'],'no_scale':True})
        else:
            qty=round(ing['quantity']*factor,1)
            prot=round(ing['protein']*factor,1) if ing['protein'] is not None else None
            scaled.append({'name':ing['name'],'quantity':qty,'unit':ing['unit'],'protein':prot,'no_scale':False})

    resp={'scaling_type':stype,'factor':round(factor,1),'scaled_ingredients':scaled}
    if result_pps is not None: resp['new_pps']=result_pps
    return jsonify(resp)

if __name__=='__main__':
    app.run(host='0.0.0.0',port=5000)