from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import UserMixin, LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from zoneinfo import ZoneInfo
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, flash, Response, url_for, jsonify, session, abort
from sqlalchemy import func, extract
from flask_admin import Admin, AdminIndexView, expose
from flask_admin.contrib.sqla import ModelView
from sqlalchemy.exc import IntegrityError
from flask_apscheduler import APScheduler

import os
import logging
import io
import random

##############################################################
# flask アプリのインスタンスを作成
app = Flask(__name__)

### LOG IN 管理システム
login_manager = LoginManager()
login_manager.init_app(app)

####################################################
app.config["SECRET_KEY"] = os.urandom(24)
default_uri = 'postgresql+psycopg://docker:docker@localhost/exampledb'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', default_uri)

db = SQLAlchemy()
db.init_app(app)

migrate = Migrate(app,db)


#//////////////////////////////////////////////////////////////////////////////////////////
#　データベースの作成
#//////////////////////////////////////////////////////////////////////////////////////////

# 1. ユーザー登録
class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    # リレーションを追加しておくと便利です
    posts = db.relationship('StudyPost', backref='author', lazy=True)

# 学習カテゴリー
class StudyCategory(db.Model):
    __tablename__ = 'study_category'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

# 3. 投稿モデル 
class StudyPost(db.Model):
    __tablename__ = 'study_post'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # 有効化
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.now)
    
    likes = db.relationship('Like', backref='post', lazy='dynamic', cascade="all, delete-orphan")
    comments = db.relationship('Comment', backref='post', lazy='dynamic', cascade="all, delete-orphan")
    details = db.relationship('StudyDetail', backref='post', lazy=True, cascade="all, delete-orphan")
    references = db.relationship('Reference', backref='post', cascade='all, delete-orphan')
    
    
class Like(db.Model):
    __tablename__ = 'likes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) 
    post_id = db.Column(db.Integer, db.ForeignKey('study_post.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# 4. カテゴリー毎の時間モデル (明細データ)
class StudyDetail(db.Model):
    __tablename__ = 'study_detail'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('study_post.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('study_category.id'), nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    # カテゴリー名を簡単に取得するためのリレーション
    category = db.relationship('StudyCategory')


# 参照データテーブル
class Reference(db.Model):
    __tablename__ = 'references'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('study_post.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('study_category.id'), nullable=True) 
    title = db.Column(db.String(200), nullable=False)
    url = db.Column(db.String(500))
    rating = db.Column(db.Integer) 
    category = db.relationship('StudyCategory', backref='reference_list')

class Comment(db.Model):
    __tablename__ = 'comments'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('study_post.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Userモデルとのリレーション（ユーザー名表示用）
    author = db.relationship('User', backref='comments')


##///////////////////////////////////////////////////////////////////////////////////////////////////////
##  ◆ 「dashboard.html」　に関する機能
##///////////////////////////////////////////////////////////////////////////////////////////////////////

########################
# ●参照データの操作 (dashboard.html)
########################
@app.route("/dashboard")
def dashboard():
    categories = StudyCategory.query.all()
    
    selected_category_id = request.args.get('category_id', type=int)
    selected_min_rating = request.args.get('min_rating', type=int) # 新しく取得

    query = Reference.query
    
    # カテゴリーで絞り込み
    if selected_category_id:
        query = query.filter(
            Reference.category.has(id=selected_category_id)
        )
    
    # おすすめ度で絞り込み
    if selected_min_rating is not None:
        # DB上の rating カラムが selected_min_rating 以上であるという条件を追加
        query = query.filter(Reference.rating >= selected_min_rating)

    references = query.all()
   
    return render_template('dashboard.html', 
                           references=references, 
                           categories=categories, 
                           selected_category_id=selected_category_id,
                           selected_min_rating=selected_min_rating)

#########################
## ●データ抽出・集計ロジック(dashboard.html)
#########################
def get_study_stats(user_id, term='month'):
    if term == 'year':
        start_date = datetime.now() - timedelta(days=365)
        fmt = 'YYYY-MM'
    else:
        start_date = datetime.now() - timedelta(days=30)
        fmt = 'YYYY-MM-DD'

    # 1. 棒グラフ用 
    time_label = func.to_char(StudyPost.created_at, fmt)
    
    bar_query = db.session.query(
        time_label.label('label'),
        func.sum(StudyDetail.duration_minutes).label('total_minutes')
    ).join(StudyDetail).filter(
        StudyPost.user_id == user_id,
        StudyPost.created_at >= start_date
    ).group_by(time_label).order_by(time_label).all()

    # 2. 円グラフ用
    pie_query = db.session.query(
        StudyCategory.name.label('label'),
        func.sum(StudyDetail.duration_minutes).label('total_minutes')
    ).join(StudyDetail).join(StudyPost).filter( 
        StudyPost.user_id == user_id,
        StudyPost.created_at >= start_date
    ).group_by(StudyCategory.name).all()

    return {
        "bar_labels": [r.label for r in bar_query],
        "bar_values": [round((r.total_minutes or 0) / 60, 1) for r in bar_query],
        "pie_labels": [r.label for r in pie_query],
        "pie_values": [r.total_minutes or 0 for r in pie_query],
        "raw_data": {
            "bar": [dict(r._mapping) for r in bar_query], 
            "pie": [dict(r._mapping) for r in pie_query]
        }
    }

#########################
## ●グラフ化パラメータ受取り(dashboard.html)
#########################
@app.route("/graph", methods=['POST'])
def handle_graph_post():
    uname = request.form.get('user_name_graph')
    term = request.form.get('disp_term_graph')
    
    session['uname'] = uname
    session['term'] = term

    return redirect('/show_dashboard')

#########################
## ●データ読出し、操作、出力(dashboard.html)
#########################
@app.route("/show_dashboard", methods=['GET'])
def show_dashboard():
    uname = session.get('uname')
    term = session.get('term')

    if not uname or not term:
        return redirect('/index')

    user = User.query.filter_by(username=uname).first()
    if not user:
        return "ユーザーが見つかりません", 404
        
    data = get_study_stats(user.id, term) 

    return render_template('dashboard_graph.html', data=data, uname=uname, term=term)

##########################
# ●指定ユーザー投稿一覧 (dashboard.html)
##########################
@app.route('/post_list/', methods=['GET','POST'])
def post_list():

    if request.method == 'POST':
        uname_plist = request.form.get('user_name_plist')
        session['user_name'] = uname_plist
    else:
        uname_plist = session.get('user_name')
        
    udata_plist = User.query.filter_by(username=uname_plist).first()
    
    if udata_plist:
        posts = StudyPost.query.filter_by(user_id=udata_plist.id).order_by(StudyPost.created_at.desc()).all()
        return render_template('post_list.html', user=udata_plist, posts=posts)
    else:
        return "ユーザーが見つかりません", 404

##///////////////////////////////////////////////////////////////////////////////////////////////////////
##  ◆ 「index.html」　に関する機能
##///////////////////////////////////////////////////////////////////////////////////////////////////////
@app.route("/")
@app.route("/index")
def index():
    posts = StudyPost.query.order_by(StudyPost.created_at.desc()).all()
    return render_template("index.html",posts=posts)

##////////////////////////////////////////////////////////////////////////////////////////////////////////////////
##  ◆ 「create_post.html」　に関する機能
##////////////////////////////////////////////////////////////////////////////////////////////////////////////////
@app.route("/create_post", methods=['GET','POST'])
@login_required
def post_study():
    if request.method == 'POST':
        # 1. 基本データの取得
        title = request.form.get('title')
        content = request.form.get('content')
        
        tokyo_now = datetime.now(ZoneInfo("Asia/Tokyo")).replace(second=0, microsecond=0, tzinfo=None)
        new_post = StudyPost(user_id=current_user.id, title=title, content=content, created_at=tokyo_now)
        db.session.add(new_post)

        # 2. 学習カテゴリー別時間の保存
        categories = request.form.getlist('category_id[]')
        durations = request.form.getlist('duration[]')
        for cat, dur in zip(categories, durations):
            if cat and dur:
                detail = StudyDetail(category_id=int(cat), duration_minutes=int(dur))
                new_post.details.append(detail)

        # 3. 参照データの保存
        ref_titles = request.form.getlist('ref_title')
        ref_urls = request.form.getlist('ref_url')
        ref_ratings = request.form.getlist('ref_rating')
        ref_cat_ids = request.form.getlist('ref_category_id')

        # zipでまとめてループ処理
        for r_title, r_url, r_rating, r_cat_id in zip(ref_titles, ref_urls, ref_ratings, ref_cat_ids):
            if not r_title: 
                continue
            
            new_ref = Reference(
                title=r_title,
                url=r_url,
                rating=int(r_rating) if r_rating else 3,
                category_id=int(r_cat_id) if r_cat_id else None,
                post=new_post 
            )
            db.session.add(new_ref)

        db.session.commit()
        flash("学習記録が正常に保存されました。", "success")
        return redirect('/')
    
    # GET時の処理
    elif request.method == 'GET':
        categories = StudyCategory.query.all()
        return render_template('create_post.html', categories=categories)

##////////////////////////////////////////////////////////////////////////////////////////////////////////////////
##  ◆ 「update.html」　に関する機能
##////////////////////////////////////////////////////////////////////////////////////////////////////////////////
@app.route('/<int:post_id>/update', methods=['GET', 'POST'])
@login_required
def update(post_id):
    post = StudyPost.query.get_or_404(post_id)
    all_categories = StudyCategory.query.all()
    
    if post.user_id != current_user.id:
        flash("編集権限がありません。", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        new_title = request.form.get('title')
        new_content = request.form.get('content')

        if not new_title:
            flash("タイトルは必須項目です。", "warning")
            return render_template('update.html', post=post, all_categories=all_categories)

        # 1. 基本情報の更新
        post.title = new_title
        post.content = new_content
        
        # 2. 学習カテゴリと時間の更新（リストをクリアして再追加）
        post.details.clear() 
        
        category_ids = request.form.getlist('category_id[]')
        durations = request.form.getlist('duration[]')
        for cat_id, dur in zip(category_ids, durations):
            if cat_id and dur:
                detail = StudyDetail(category_id=int(cat_id), duration_minutes=int(dur))
                post.details.append(detail) # post_idは自動で補完されます

        # 3. 参照データの更新
        post.references.clear()
        ref_titles = request.form.getlist('ref_title[]')
        ref_urls = request.form.getlist('ref_url[]')
        ref_ratings = request.form.getlist(f'ref_rating[]')
        ref_category_ids = request.form.getlist('ref_category[]') 
        
        for r_title, r_url, r_rating, r_cat_id in zip(ref_titles, ref_urls, ref_ratings, ref_category_ids):
            if r_title:
                ref = Reference(
                    title=r_title, 
                    url=r_url, 
                    rating=int(r_rating) if r_rating else 3,
                    category_id=int(r_cat_id) if r_cat_id else None
                )
                post.references.append(ref)

        db.session.commit()
        return redirect('/index')

    elif request.method == 'GET':
        return render_template('update.html', post=post, all_categories=all_categories)

##////////////////////////////////////////////////////////////////////////////////////////////////////////////////
##  ◆ 「readmore.html」　に関する機能
##////////////////////////////////////////////////////////////////////////////////////////////////////////////////
@app.route('/<int:post_id>/readmore')
def readmore(post_id):
    post = StudyPost.query.get_or_404(post_id)
    return render_template("readmore.html",post=post)

########################
# ●ポスト削除 (readmore.html)
########################
@app.route('/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    post = StudyPost.query.get_or_404(post_id)
    # 投稿者チェック
    if post.user_id != current_user.id:
        abort(403)
    db.session.delete(post)
    db.session.commit()
    return redirect('/index')

########################
# ●コメント機能 (readmore.html)
########################
@app.route('/<int:post_id>/comment', methods=['POST'])
@login_required
def post_comment(post_id):
    post = StudyPost.query.get_or_404(post_id)
    content = request.form.get('content')

    if not content:
        flash('コメント内容を入力してください。', 'danger')
    else:
        new_comment = Comment(
            content=content,
            user_id=current_user.id,
            post_id=post.id
        )
        db.session.add(new_comment)
        db.session.commit()
        flash('コメントを投稿しました。', 'success')
        
    return redirect(f"/{post_id}/readmore")


########################
# ●いいね機能 (readmore.html)
########################
# ★要修正、URLとハート型への対応が必要
########################
@app.route('/post/<int:post_id>/like', methods=['POST'])
@login_required
def toggle_like(post_id):
    print(f"DEBUG: Post {post_id} にいいねが押されました！") 
    post = StudyPost.query.get_or_404(post_id)
    like = Like.query.filter_by(user_id=current_user.id, post_id=post_id).first()

    if like:
        # 既にいいねしていれば解除
        db.session.delete(like)
        status = 'unliked'
    else:
        # いいねを付与
        new_like = Like(user_id=current_user.id, post_id=post_id)
        db.session.add(new_like)
        status = 'liked'
    
    db.session.commit()
    
    return jsonify({
        'status': 'success',
        'action': status,
        'like_count': post.likes.count()
    })

##////////////////////////////////////////////////////////////////////////////////////////////////////////////////
## ◆ ログイン関連
##////////////////////////////////////////////////////////////////////////////////////////////////////////////////

#####################################
# 起動時に管理者を作成する関数
#####################################
def create_admin():
    admin_username = "admin"
    admin_password = "admin"

    # すでに同名のユーザーがいるか確認
    existing_admin = User.query.filter_by(username=admin_username).first()
    
    if not existing_admin:
        hashed_pw = generate_password_hash(admin_password)
        new_admin = User(
            username=admin_username, 
            password=hashed_pw, 
            is_admin=True
        )
        db.session.add(new_admin)
        db.session.commit()
        print(f"管理者 '{admin_username}' を作成しました。")
    else:
        print("管理者は既に存在します。")

#####################################
# アクセスを管理者のみに制限する機能
#####################################
def admin_required(f):
    @wraps(f)
    @login_required

    def decorated_function(*args, **kwargs):
        # 現在ログインしているユーザーの is_admin 属性を確認する
        if current_user.is_admin:
            return f(*args, **kwargs)
        else:
            flash('管理者権限が必要です。', 'warning')
            return redirect('/login')

    return decorated_function

#####################################
##　現在のユーザを識別する関数
#####################################
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

#####################################
@app.route("/login", methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect('/index')
        else:
            flash('ユーザー名またはパスワードが違います', 'error')
            return redirect('/login')

    elif request.method == 'GET':
        return render_template('login.html')


##////////////////////////////////////////////////////////////////////////////////////////////////////////////////
##  ◆ 「administrator.html」　に関する機能
##////////////////////////////////////////////////////////////////////////////////////////////////////////////////

########################
# ● 「administrator.html」前の処理
########################
@app.route("/administrator")
@admin_required
def administrator():
    target_user = session.get('last_operated_user', '')
    users = db.session.execute(db.select(User).order_by(User.username)).scalars()
    category_data = StudyCategory.query.all()
    return render_template("administrator.html",
                                      users=users, categories=category_data,
                                      auto_post_status=auto_post_status,
                                      target_user=target_user
                                      )

########################
# ●学習カテゴリ追加 (administrator.html)
########################
@app.route("/create_category", methods=['POST'])
@admin_required
def create_category():
    add_cat_name = request.form.get('category_name')
    existing_category = StudyCategory.query.filter_by(name=add_cat_name).first()

    if existing_category:
        flash('そのカテゴリ名はすでに登録されています。', 'danger')
        return redirect('/administrator')
    else:
        add_cad_data = StudyCategory(name=add_cat_name)
        db.session.add(add_cad_data)
        db.session.commit()
        flash('新しいカテゴリを登録しました。', 'success') 
        return redirect('/administrator')

########################
# ●学習カテゴリ削除 (administrator.html)
########################
@app.route("/delete_category", methods=['POST'])
@admin_required
def delete_category():
    del_cat_id = request.form.get('category_id')
    del_cat_data = StudyCategory.query.get(int(del_cat_id))
    db.session.delete(del_cat_data)
    db.session.commit()
    return redirect('/administrator')


########################
# ●user 追加 (administrator.html)
########################
@app.route("/create_account", methods=['POST'])
@admin_required
def create_account():
    username = request.form.get('add_user_name')
    password = request.form.get('add_user_pass')
    
    # ユーザー名が既に存在するかチェック
    existing_user = User.query.filter_by(username=username).first()
    
    if existing_user:
        # 存在する場合はエラーメッセージを表示してリダイレクト
        flash(f'ユーザー名 "{username}" は既に使用されています。', 'error')
        return redirect('/administrator')
    else:
        # 存在しない場合は新規登録処理を続行
        hashed_pass = generate_password_hash(password)
        user = User(username=username, password=hashed_pass)
        db.session.add(user)
        db.session.commit()
        flash(f'ユーザー "{username}" を登録しました。', 'success')
        return redirect('/administrator')

########################
# ●user 削除 (administrator.html)
########################
@app.route("/delete_account", methods=['POST'])
@admin_required
def delete():
    del_name = request.form.get('del_user_name')
    
    if del_name:
        del_udata = User.query.filter_by(username=del_name).first()
        
        if del_udata:
            db.session.delete(del_udata)
            db.session.commit()
            # サーバーコンソールではなく、ブラウザに成功メッセージを表示
            flash(f'ユーザー "{del_name}" を削除しました。', 'success')
        else:
            # サーバーコンソールではなく、ブラウザにエラーメッセージを表示
            flash(f'ユーザー名 "{del_name}" が見つかりませんでした。', 'error')
            
    return redirect(url_for('administrator'))
    
########################
# ●「Flask-Admin」のカスタマイズ
########################
class CustomAdminIndexView(AdminIndexView):
    @expose('/')
    def index(self):
        total_users = User.query.count()
        total_records = StudyPost.query.count()
        return self.render('admin/custom_index.html', 
                            total_users=total_users,
                            total_records=total_records)

    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin
    
    def _handle_view(self, name, **kwargs):
        if not self.is_accessible():
            return redirect(url_for('login', next=request.url))


app.config['FLASK_ADMIN_SWATCH'] = 'cerulean' 
admin = Admin(app, name='<Flask-Admin>', index_view=CustomAdminIndexView(name='Home'))

# 管理画面にモデルを追加
admin.add_view(ModelView(User, db.session))
admin.add_view(ModelView(StudyPost, db.session))
admin.add_view(ModelView(StudyDetail, db.session))
admin.add_view(ModelView(StudyCategory, db.session))
admin.add_view(ModelView(Reference, db.session))
admin.add_view(ModelView(Comment, db.session))

########################
# ●ログアウト機能
########################
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect('/login')

########################
# ●エラー処理
########################
@app.errorhandler(404)
def not_found_error(error):
    return render_template('error.html', message='お探しのページは見つかりませんでした。'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback() 
    return render_template('error.html', message='サーバー内部で予期せぬエラーが発生しました。'), 500

@app.errorhandler(IntegrityError)
def handle_integrity_error(e):
    return render_template('error.html', message='データベースエラーが発生しました。管理者にお問い合わせください。'), 400

########################
# ●1日1回の自動投稿を行う関数
########################

# スケジューラの初期化
scheduler = APScheduler()

# 実行状態を保持するシンプルなモデル例（既にDBがあれば、設定値を保存するテーブルに追加してください）
# 今回は簡易的にグローバル変数で「実行中フラグ」を管理する例ですが、
# 本来はDBのUserテーブル等に 'is_auto_post_enabled' カラムを作るのが理想です。
auto_post_status = {} # { "username": True/False }

def auto_post_task(app, uname):
    """1日1回実行される実際の処理"""
    with app.app_context():
        udata = User.query.filter_by(username=uname).first()
        if udata:
            # 今日の分のデータを生成
            today = datetime.now()
            categories_demo = [1, 2, 3, 4]
            durations_demo = [random.randint(10, 60) for _ in range(4)]
            
            title_val = f"{today.strftime('%Y-%m-%d')} の自動学習記録"
            cont_val = "自動投稿：今日の学習も順調です！"
            
            new_post = StudyPost(user_id=udata.id, content=cont_val, title=title_val, created_at=today)
            db.session.add(new_post)
            
            for j, (cat, dur) in enumerate(zip(categories_demo, durations_demo), 1):
                detail = StudyDetail(category_id=cat, duration_minutes=dur)
                new_post.details.append(detail)
            
            db.session.commit()
            print(f"AUTO TASK: {uname} の投稿を完了しました")

########################
# ●ダミーデータの生成 (administrator.html)
########################
# スケジュール機能のON/OFFを切り替えるルート
@app.route("/toggle_auto_post", methods=['POST'])
def toggle_auto_post():
    uname = request.form.get('user_name_dummy')
    action = request.form.get('action')
    
    # 最後に操作したユーザー名をセッションに保存する
    if uname:
        session['last_operated_user'] = uname
    
    # ... (ユーザー存在確認などの既存ロジック) ...
    udata = User.query.filter_by(username=uname).first()
    if not udata:
        flash(f"ユーザー {uname} が見つかりません", "error")
        return redirect(url_for('administrator'))
        
    job_id = f"job_{uname}"

    if action == 'start':
        # ... (scheduler.add_job のロジック) ...
        auto_post_status[uname] = True
        flash(f"{uname} の自動投稿を開始しました", "success")
    else:
        # ... (scheduler.remove_job のロジック) ...
        auto_post_status[uname] = False
        flash(f"{uname} の自動投稿を停止しました", "info")
    
    return redirect('/administrator')

########################
# ●ダミーデータの生成 (administrator.html)
########################
@app.route("/dummy_data_gen", methods=['POST'])
def dummy_data_gen():
    # 1. HTMLのフォームから値を取得
    uname = request.form.get('user_name_dummy')  # ユーザー名
    gen_type = request.form.get('gen_data_pat') # 選択された処理の種類
    today = datetime.now()
    categories_demo = [1, 2, 3, 4]

    # 2. ユーザーの存在確認
    udata = User.query.filter_by(username=uname).first()
    if not udata:
        flash(f'ユーザー名 "{uname}" が見つかりませんでした。', 'error')
        return redirect('/administrator')


    if gen_type == 'grp_dat_gen':
        
        for i in range(365):
            target_date = today - timedelta(days=i)
            durations_demo = [random.randint(10, 60) for _ in range(4)] 
            title_val = f"{target_date.strftime('%Y-%m-%d')} の学習記録"
            cont_val = f"今日は{target_date.day}日目の学習です。継続中！"
            
            new_post = StudyPost(user_id=udata.id, content=cont_val, title=title_val, created_at=target_date)
            db.session.add(new_post)
            
            # 子データの作成
            for j, (cat, dur) in enumerate(zip(categories_demo, durations_demo), 1):
                dur_final = int(dur) + i + j + udata.id
                detail = StudyDetail(category_id=cat, duration_minutes=int(dur_final))
                new_post.details.append(detail)
        
        db.session.commit()
#        print(f"DEBUG: {uname} に対してグラフ用データを生成しました")

    elif gen_type == 'ref_dat_gen':
        for i in range(16):
            target_date = today - timedelta(days=i)
            durations_demo = [random.randint(10, 60) for _ in range(4)] 
            title_val = f"{target_date.strftime('%Y-%m-%d')} の学習記録(参照データ付き)"
            cont_val = f"今日は{target_date.day}日目の学習です。継続中！"
            
            new_post = StudyPost(user_id=udata.id, content=cont_val, title=title_val, created_at=target_date)
            db.session.add(new_post)
            
            for j, (cat, dur) in enumerate(zip(categories_demo, durations_demo), 1):
                dur_final = int(dur) + i + j + udata.id
                detail = StudyDetail(category_id=cat, duration_minutes=int(dur_final))
                new_post.details.append(detail)
            #######################################################
            raw_data = [
                ['【WebAPIやWebデータ自動取得完全攻略】', 'https://www.youtube.com/watch?v=iOXcJoAtXn4', 5, 2],
                ['【Python×FlaskでWebアプリ開発】', 'https://www.youtube.com/watch?v=cxgY9mKDuHw', 5, 2],
                ['【Python副業完全攻略】', 'https://www.youtube.com/watch?v=kV8fpcXo73s', 5, 2],
                ['【Python環境構築完全攻略】', 'https://www.youtube.com/watch?v=BLMc1reLeGc', 5, 1],
                ['【FlaskによるバックエンドAPIの基礎#4】', 'https://www.youtube.com/watch?v=wKZmbMZJQ-s', 3, 1],
                ['【Docker超入門：Windows上にLinux環境を作ろう】', 'https://www.youtube.com/watch?v=iRAy0h5HpZA', 3, 1],
                ['【Docker超入門：コンテナを使ったPython開発環境の構築】', 'https://www.youtube.com/watch?v=CCcF5xuaDtI', 3, 2],
                ['【Docker超入門：コンテナ内でコマンドを実行する2つの方法】', 'https://www.youtube.com/watch?v=PR_JMxvyyfA', 3, 4],
                ['【Dockerのコンテナ型の仮想環境を作ろう！】', 'https://www.youtube.com/watch?v=B5tSZr_QqXw', 3, 4],
                ['【Python入門】プログラミングの基本を2時間半で学ぶ！', 'https://www.youtube.com/watch?v=tCMl1AWfhQQ', 4, 4],
                ['【Pythonでデスクトップアプリ(Excel)を10分で作成！】', 'https://www.youtube.com/watch?v=dPK5xNRUOuI', 4, 3],
                ['【Python】Flaskでつくる5ちゃんねる風掲示板Webアプリ(Part1)', 'https://www.youtube.com/watch?v=DkOZSxaMV8w', 4, 3],
                ['【入門講座】PythonのPandasの使い方について徹底的にまとめていく！', 'https://www.youtube.com/watch?v=sSR2x0y6D9s', 4, 2],
                ['【入門講座】PythonのMatplotlibの使い方について徹底的にまとめていく！', 'https://www.youtube.com/watch?v=6-QCxoA3Rio', 4, 2],
                ['【Python入門】JupyterLab Desktop完全攻略！！【データ分析・機械学習】', 'https://www.youtube.com/watch?v=d_OVFb3gL_8', 4, 1],
                ['Pandas入門　①読込，抽出【研究で使うPython #53】', 'https://www.youtube.com/watch?v=GoboWIxBBWw', 4, 1],
            ]
            t, u, r, c = raw_data[i]
            new_ref = Reference(
                title=t,
                url=u,
                rating=r,
                category_id=c
            )
            new_post.references.append(new_ref)
            db.session.add(new_ref)
        #######################################################
        db.session.commit()
    return redirect('/administrator')


########################
# ●実行
########################
logging.basicConfig(level=logging.DEBUG) 
#アプリケーションを実行
if __name__ == "__main__":
    with app.app_context():
        db.create_all()  # テーブル作成
        create_admin()   # 管理者作成
    app.run(debug=True, host="0.0.0.0", port=5000)

##////////////////////////////////////////////////////////////////////////////////////////////////////////

