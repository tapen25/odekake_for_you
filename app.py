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

    # 日時と予算
    date_time_input = request.form.get('date_time')
    budget_val = request.form.get('budget')

    # リスト形式データの取得
    raw_stations = request.form.getlist('stations') # ★一度そのまま取得
    attributes = request.form.getlist('attribute')
    purposes = request.form.getlist('purpose')
    access = request.form.getlist('access')
    vibes = request.form.getlist('vibes')
    mobilities = request.form.getlist('mobility[]') 
    ng_conditions = request.form.getlist('ng[]')
    people_types = request.form.getlist('people_type[]')

    # --- 2. データの整形 ---
    
    # ★変更点1：駅名リストから空文字（未入力）を除去
    # strip()を使うことで、スペースのみの入力も弾きます
    stations = [s for s in raw_stations if s.strip()]

    # 日時のフォーマット整形
    formatted_date = "未定"
    if date_time_input:
        try:
            dt_obj = datetime.strptime(date_time_input, '%Y-%m-%dT%H:%M')
            formatted_date = dt_obj.strftime('%Y年%m月%d日 %H:%M')
        except ValueError:
            formatted_date = date_time_input

    # 予算コードを日本語に変換
    budget_map = {
        "cheap": "なるべく安く（〜2,000円）",
        "3000": "3,000円以内",
        "5000": "5,000円以内",
        "10000": "10,000円以内",
        "luxury": "リッチに（1万円以上）",
        "unspecified": "指定なし"
    }
    budget_str = budget_map.get(budget_val, "指定なし")

    # メンバー内訳を日本語に変換
    pt_map = {"adult": "大人", "child": "子ども", "senior": "高齢者"}
    people_types_str = ", ".join([pt_map.get(p, p) for p in people_types])

    # 情報を文字列に結合
    stations_str = ", ".join(stations) if stations else "指定なし" # ★空の場合の文言
    attributes_str = ", ".join(attributes) + (f" ({attribute_other})" if attribute_other else "")
    purposes_str = ", ".join(purposes) + (f" ({purpose_other})" if purpose_other else "")
    vibes_str = ", ".join(vibes) + (f" ({vibes_other})" if vibes_other else "")
    ng_str = ", ".join(ng_conditions)
    mobility_str = ", ".join(mobilities)
    access_str = ", ".join(access)

    # ★変更点2：駅入力の有無でAIへの指示（route_instruction）を分岐させる
    if stations:
        # 駅入力がある場合：アクセス経路を表示させる指示
        route_instruction = """
        【集合場所へのルート表示】
        メンバーそれぞれの出発駅が異なるため、以下のHTML構造を使って表示してください。
        入力された最寄駅の数だけ <div class="route-card"> を作成してください。
        
        <div class="route-container">
            <div class="route-card">
                <h4>メンバー（最寄駅名）</h4>
                <p>ここにルート、所要時間、運賃を記載</p>
            </div>
        </div>
        
        ※その下に、全員が合流する「集合場所」と「集合時間」を明記してください。
        """
    else:
        # 駅入力がない場合：集合場所からのスタートにする指示
        route_instruction = """
        【集合場所の提案】
        最寄駅の指定がないため、個別の移動ルートは省略してください。
        全員が合流しやすい「集合場所」と「集合時間」の提案からプランを開始してください。
        """

    # --- 3. プロンプト作成 ---
    prompt = f"""
    あなたはプロのトラベルプランナーです。以下の条件で最高のお出かけプランを作成してください。

    【基本情報】
    - 目的地: {place}
    - 予定日時: {formatted_date}
    - 予算(1人あたり): {budget_str}
    - 人数: {num_people}人
    - 同行者: {partner}
    - メンバー構成詳細: {people_types_str} 
    - メンバー最寄駅リスト: {stations_str}

    【条件・こだわり】
    - 属性: {attributes_str}
    - 用途: {purposes_str}
    - 交通手段: {access_str}
    - 移動のこだわり: {mobility_str}
    - 雰囲気: {vibes_str}
    - 食事: {meal} (ジャンル: {meal_genre})

    【NG条件】
    - {ng_str}

    【重要：店舗・スポットの選定ルール】
    1. **必ず「実在する店（飲食店など）や・場所」のみ**を提案してください。架空の店名は禁止です。
    2. 提案する全てのスポット（集合場所、観光地、飲食店など）について、**Googleマップの検索用URL**を埋め込んでください。
    3. URLの形式は `https://www.google.com/maps/search/?api=1&query=スポット名` としてください。
    4. 「メンバー構成詳細」や「NG条件」を考慮し、例えば子どもや高齢者がいる場合は歩きやすさや休憩場所、子ども向け施設などを考慮してください。

    【出力形式の指示】
    HTML形式で出力してください（<html>タグは不要）。
    <div>タグで囲み、以下の構成にしてください。

    1. プラン全体のタイトル (<h3>)
    2. {route_instruction}
    3. タイムスケジュール (<ul><li>)
       - ※開始時間は {formatted_date} の時間を基準にする。
       - ※各スポット名の横に <a href="GoogleマップURL" target="_blank" style="color:#007bff; text-decoration:none; margin-left:5px;">[地図]</a> を配置する。
    4. 各スポットのおすすめポイントと選定理由 (<p>)
    """

    ai_text = ""

    # --- 4. OpenAI API 呼び出し ---
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "あなたは優秀な旅行プランナーです。HTMLタグを使って見やすく出力します。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
        )

        ai_text = response.choices[0].message.content
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

    # --- 5. 結果表示 ---
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