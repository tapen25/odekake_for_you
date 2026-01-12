import os
from datetime import datetime
from flask import Flask, render_template, request
from dotenv import load_dotenv
from openai import OpenAI
from flask_sqlalchemy import SQLAlchemy

# .env ファイルの読み込み
load_dotenv()

app = Flask(__name__)

# -------------------------
# DB 設定
# -------------------------
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///trip.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class SearchHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    destination = db.Column(db.String(100), nullable=False)
    plan_result = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

# アプリ起動時にテーブルを作成
with app.app_context():
    db.create_all()

# -------------------------
# OpenAI 設定
# -------------------------
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
)

# -------------------------
# ルーティング
# -------------------------
@app.route('/')
def index():
    # 入力画面へリダイレクト、もしくはトップページを表示
    return render_template('index.html')


@app.route('/input')
def input_page():
    return render_template('input.html')

@app.route('/result', methods=['POST'])
def result():
    # --- 1. フォームデータの取得 ---
    place = request.form.get('place')
    num_people = request.form.get('num_people')
    partner = request.form.get('partner')
    meal = request.form.get('meal')
    meal_genre = request.form.get('meal_genre')
    attribute_other = request.form.get('attribute_other')
    purpose_other = request.form.get('purpose_other')
    vibes_other = request.form.get('vibes_other')

    # リスト形式（getlistを使用）
    stations = request.form.getlist('stations')
    attributes = request.form.getlist('attribute')
    purposes = request.form.getlist('purpose')
    access = request.form.getlist('access')
    vibes = request.form.getlist('vibes')
    
    # HTML側で name="mobility[]" となっている場合、キー名に [] を含める必要があります
    mobilities = request.form.getlist('mobility[]') 
    ng_conditions = request.form.getlist('ng[]')

    # --- 2. プロンプト作成 ---
    # 情報を文字列に整形
    stations_str = ", ".join([s for s in stations if s])
    attributes_str = ", ".join(attributes) + (f" ({attribute_other})" if attribute_other else "")
    purposes_str = ", ".join(purposes) + (f" ({purpose_other})" if purpose_other else "")
    vibes_str = ", ".join(vibes) + (f" ({vibes_other})" if vibes_other else "")
    ng_str = ", ".join(ng_conditions)
    mobility_str = ", ".join(mobilities)
    access_str = ", ".join(access)

    route_instruction = """
    【集合場所へのルート表示】
    メンバーそれぞれの出発駅が異なるため、以下のHTML構造を使って表示してください。
    人数（駅数）分だけ <div class="route-card"> を繰り返して作成してください。
    
    <div class="route-container">
        <div class="route-card">
            <h4>メンバー1（最寄駅名）</h4>
            <p>ここにルート、所要時間、運賃を記載</p>
        </div>
        <div class="route-card">
            <h4>メンバー2（最寄駅名）</h4>
            <p>ここにルート、所要時間、運賃を記載</p>
        </div>
        </div>
    
    ※その下に、全員が合流する「集合場所」と「集合時間」を明記してください。
    """

    # 全体のプロンプト組み立て
    prompt = f"""
    あなたはプロのトラベルプランナーです。以下の条件で最高のお出かけプランを作成してください。

    【基本情報】
    - 目的地: {place}
    - 人数: {num_people}人
    - 同行者: {partner}
    - メンバー最寄駅リスト: {stations_str}

    【条件・こだわり】
    - 属性: {attributes_str}
    - 用途: {purposes_str}
    - 交通: {access_str}
    - 移動のこだわり: {mobility_str}
    - 雰囲気: {vibes_str}
    - 食事: {meal} (ジャンル: {meal_genre})

    【NG条件】
    - {ng_str}

    【出力形式の指示】
    HTML形式で出力してください（<html>タグは不要）。
    <div>タグで囲み、以下の構成にしてください。

    1. プラン全体のタイトル (<h3>)
    2. {route_instruction}
    3. タイムスケジュール (<ul><li>)
    4. 各スポットのおすすめポイントと選定理由 (<p>)
    """

    ai_text = ""

    # --- 3. OpenAI API 呼び出し & DB保存 ---
    try:
        response = client.chat.completions.create(
            model="gpt-4o", # 精度重視ならgpt-4o, コスト重視ならgpt-3.5-turbo
            messages=[
                {"role": "system", "content": "あなたは優秀な旅行プランナーです。HTMLタグを使って見やすく出力します。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
        )

        ai_text = response.choices[0].message.content
        
        # 不要なマークダウン記号（```html 等）の削除
        ai_text = ai_text.replace("```html", "").replace("```", "").strip()

        # 履歴保存
        new_history = SearchHistory(
            destination=place,
            plan_result=ai_text
        )
        db.session.add(new_history)
        db.session.commit()

    except Exception as e:
        print(f"Error: {e}")
        ai_text = f"<p>申し訳ありません。プランの生成中にエラーが発生しました。<br>詳細: {e}</p>"

    # --- 4. 結果表示 ---
    return render_template(
        'result.html',
        plan=ai_text,
        place=place
    )

@app.route('/history')
def history():
    histories = SearchHistory.query.order_by(
        SearchHistory.created_at.desc()
    ).all()
    return render_template('history.html', histories=histories)

if __name__ == '__main__':
    app.run(debug=True, port=5000)