import os, random
import sqlite3
from flask import Flask, flash, redirect, render_template, request, url_for, send_from_directory, g
from werkzeug.utils import secure_filename
import shutil
from pytubefix import YouTube
import subprocess

app = Flask(__name__)
app.secret_key = "bingchilling"

ALLOWED = {"mp3", "wav", "ogg"}

app.config["UF"] = os.path.join(app.root_path, "static", "songs")
app.config["DB"] = "music.db"

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(app.config["DB"])
        db.row_factory = sqlite3.Row
    return db

def allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED

def make_dbs():
    with app.app_context():
        db = get_db()
        cur = db.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS playlists (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, name TEXT NOT NULL UNIQUE)")
        cur.execute("CREATE TABLE IF NOT EXISTS songs (p_id INTEGER NOT NULL, songorder INTEGER NOT NULL, s_name TEXT NOT NULL, file TEXT NOT NULL, UNIQUE (p_id, s_name), FOREIGN KEY (p_id) REFERENCES playlists(id))")
        db.commit()

@app.teardown_appcontext
def close_connection(exception=None):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

make_dbs()

@app.route("/songs/<filename>")
def song_files(filename):
    return send_from_directory(app.config["UF"], filename)

@app.route("/")
def index():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM playlists")
    playlists = cur.fetchall()
    return render_template("index.html", playlists=playlists)


@app.route("/addsong", methods=["POST"])
def addsong():
    db = get_db()
    cur = db.cursor()

    playlist_id = request.form.get("id")
    name = request.form.get("name")
    file = request.files.get("file")

    if not name:
        return render_template("error.html", msg="Name required")

    if len(name) > 50:
        return render_template("error.html", msg="Name must be 50 characters or under")

    
    folder = os.path.join(app.config["UF"], f"playlist_{playlist_id}")
    if not os.path.exists(folder):
        return render_template("error.html", msg="Playlist does not exist")
    
    if file and allowed(file.filename):
        filename = secure_filename(file.filename)
        path = os.path.join(folder, filename)
        file.save(path)

    else:
        return render_template("error.html", msg="Invalid file")


    relpath = os.path.join(f"playlist_{playlist_id}", filename).replace("\\", "/")

    cur.execute("SELECT MAX(songorder) AS maxorder FROM songs WHERE p_id=?", (playlist_id,))
    maxorder = cur.fetchone()["maxorder"]
    if maxorder is None:
        next = 1
    else:
        next = maxorder + 1

    try:
        cur.execute("INSERT INTO songs (p_id, songorder, s_name, file) VALUES(?, ?, ?, ?)", (playlist_id, next, name, relpath))
        db.commit()
    except sqlite3.IntegrityError:
        return render_template("error.html", msg="Another song already has this name")

    return redirect(url_for('playlist', playlist_id=playlist_id))


@app.route("/create", methods=["POST"])
def create():
    db = get_db()
    cur = db.cursor()

    name = request.form.get("name")
    if not name:
         return render_template("error.html", msg="Please enter a name")

    try:
        cur.execute("INSERT INTO playlists (name) VALUES (?)", (name,))
        db.commit()
        cur.execute("SELECT id FROM playlists WHERE name=?", (name,))
        playlist_id = cur.fetchone()["id"]
    except sqlite3.IntegrityError:
        return render_template("error.html", msg="Playlist with that name already exists")

    folder = os.path.join(app.config["UF"], f"playlist_{playlist_id}")
    if not os.path.exists(folder):
        os.makedirs(folder)

    return redirect("/")

@app.route("/deleteplaylist", methods=["POST"])
def deleteplaylist():
    db = get_db()
    cur = db.cursor()

    playlist_id = request.form.get("p_id")
    path = os.path.join(app.config["UF"], f"playlist_{playlist_id}")
    if not os.path.exists(path):
        return render_template("error.html", msg="Could not locate folder")

    for filename in os.listdir(path):
        filepath = os.path.join(path, filename)
        try:
            os.remove(filepath)
        except OSError as error:
            return render_template("error.html", msg=f"{path} - {error.strerror}")

    try:
        shutil.rmtree(path)
    except OSError as error:
        return render_template("error.html", msg=f"{path} - {error.strerror}")

    cur.execute("DELETE FROM songs WHERE p_id=?", (playlist_id,))
    cur.execute("DELETE FROM playlists WHERE id=?", (playlist_id,))

    db.commit()

    return redirect("/")

@app.route("/deletesong", methods=["POST"])
def deletesong():
    db = get_db()
    cur = db.cursor()

    playlist_id = request.form.get("plid")
    name = request.form.get("song")
    cur.execute("SELECT file FROM songs WHERE p_id=? AND s_name=?", (playlist_id, name))
    file = cur.fetchone()["file"]
    if not file:
        return render_template("error.html", msg="Could not locate file")

    path = os.path.join(app.config["UF"], file)

    try:
        os.remove(path)
    except OSError as error:
        return render_template("error.html", msg=f"{path} - {error.strerror}")

    cur.execute("DELETE FROM songs WHERE p_id=? AND s_name=?", (playlist_id, name))

    cur.execute("SELECT s_name FROM songs WHERE p_id=? ORDER BY songorder", (playlist_id,))
    remaining = cur.fetchall()

    for index, song in enumerate(remaining, start=1):
        cur.execute("UPDATE songs SET songorder=? WHERE p_id=? AND s_name=?", (index, playlist_id, song["s_name"]))

    db.commit()

    return redirect(url_for("playlist", playlist_id=playlist_id))


@app.route("/playlist/<int:playlist_id>")
def playlist(playlist_id):
    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT name FROM playlists WHERE id=?", (playlist_id,))
    playlist = cur.fetchall()
    if not playlist:
        return render_template("error.html", msg="Playlist not found")

    name = playlist[0][0]

    cur.execute("SELECT * FROM songs WHERE p_id=? ORDER BY songorder", (playlist_id,))
    songs = cur.fetchall()

    return render_template("playlist.html", name=name, songs=songs, playlist_id=playlist_id)

@app.route("/renameplaylist", methods=["POST"])
def renameplaylist():
    db = get_db()
    cur = db.cursor()

    playlistid = request.form.get("playlistid")
    newname = request.form.get("newname")

    if not newname:
        return render_template("error.html", msg="Name required")

    if len(newname) > 50:
        return render_template("error.html", msg="Name must be 50 characters or under")

    cur.execute("UPDATE playlists SET name=? WHERE id=?", (newname, playlistid))   
    db.commit()

    return redirect("/")

@app.route("/renamesong", methods=["POST"])
def renamesong():
    db = get_db()
    cur = db.cursor()

    playlist_id = request.form.get("playid")
    name = request.form.get("currentname")
    newname = request.form.get("newname")

    if not newname:
        return render_template("error.html", msg="Name required")

    if len(newname) > 50:
        return render_template("error.html", msg="Name must be 50 characters or under")
    
    cur.execute("SELECT COUNT(*) FROM songs WHERE p_id=? AND s_name=?", (playlist_id, newname))
    if cur.fetchone()[0] > 0:
        return render_template("error.html", msg="A song with this name already exists in the playlist")

    cur.execute("UPDATE songs SET s_name=? WHERE p_id=? AND s_name=?", (newname, playlist_id, name))
    db.commit()

    return redirect(url_for("playlist", playlist_id=playlist_id))

@app.route("/shuffle", methods=["POST"])
def shuffle():
    db = get_db()
    cur = db.cursor()

    playlist_id = request.form.get("playlist_id")
    cur.execute("SELECT s_name FROM songs WHERE p_id=?", (playlist_id,))
    songs = cur.fetchall()
    songnames = [song[0] for song in songs]
    random.shuffle(songnames)

    for new, songname in enumerate(songnames, start=1):
        cur.execute("UPDATE songs SET songorder = ? WHERE p_id=? AND s_name=?", (new, playlist_id, songname))
    
    db.commit()

    return redirect(url_for("playlist", playlist_id=playlist_id))
