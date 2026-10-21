"""
phoneapp.py — build "Anya" as an installable Android APK.

This is the phone *client*: a small native Compose chat app that talks to the
Anya running on your PC (over Wi-Fi, Tailscale, or the tunnel).  It is a
separate Gradle project from the Projects sandbox because it is Anya's own
artefact, not a user project — it lives under `S:\\anya-projects\\anya-phone`
so it still sits inside the one workspace the rest of the app trusts.

The app is deliberately dependency-light: Compose + Material 3 + a hand-rolled
HTTP/SSE client built on `HttpURLConnection`, so no extra networking libraries
have to resolve at build time.

Everything here is standard library; the heavy lifting (Gradle, the Android
SDK, the JDK) is discovered the same way `projects.py` does it, and that module
runs the actual build so the allow-list and environment stay identical.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
from pathlib import Path

import projects
from projects import ProjectError

# --- where the phone app lives ---------------------------------------------

PROJECT_ID = "anya-phone"
APP_NAME = "Anya"
DEFAULT_KEY = ""            # filled from config at build time

# only one Gradle build at a time; a second request gets a 409
_build_lock = threading.Lock()

_ICON_PNG = Path(__file__).resolve().parent.parent / "anya.png"


def app_dir() -> Path:
    return projects._ROOT / PROJECT_ID


# --- Kotlin sources ---------------------------------------------------------

_MAIN_ACTIVITY = r'''package com.anya.phone

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.anya.phone.ui.theme.AnyaTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            AnyaTheme {
                Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    AnyaApp()
                }
            }
        }
    }
}

/** A single line in the conversation. */
data class Msg(val from: String, var text: String)

@Composable
fun AnyaApp() {
    val store = remember { Prefs.current }
    var url by remember { mutableStateOf(store.url) }
    var key by remember { mutableStateOf(store.key) }
    var connected by remember { mutableStateOf(store.url.isNotBlank()) }

    if (!connected) {
        ConnectScreen(
            initialUrl = url,
            initialKey = key,
            onConnect = { u, k ->
                store.save(u, k)
                url = u.trimEnd('/')
                key = k
                connected = true
            },
        )
        return
    }
    ChatScreen(url, key, onForget = {
        store.save("", "")
        connected = false
    })
}

@Composable
fun ConnectScreen(initialUrl: String, initialKey: String, onConnect: (String, String) -> Unit) {
    var url by remember { mutableStateOf(if (initialUrl.isBlank()) "http://192.168.1.177:8091" else initialUrl) }
    var key by remember { mutableStateOf(initialKey) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf("") }

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text("Anya", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(6.dp))
        Text(
            "Point this at the Anya running on your PC.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(20.dp))
        OutlinedTextField(
            value = url,
            onValueChange = { url = it },
            label = { Text("Address") },
            placeholder = { Text("http://192.168.1.177:8091") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            value = key,
            onValueChange = { key = it },
            label = { Text("Key") },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            modifier = Modifier.fillMaxWidth(),
        )
        if (error.isNotBlank()) {
            Spacer(Modifier.height(10.dp))
            Text(error, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
        }
        Spacer(Modifier.height(20.dp))
        Button(
            onClick = {
                busy = true
                error = ""
                AnyaApi(url.trimEnd('/'), key).check { ok, why ->
                    busy = false
                    if (ok) onConnect(url, key) else error = why
                }
            },
            enabled = !busy && url.isNotBlank(),
            modifier = Modifier.fillMaxWidth(),
        ) { Text(if (busy) "Checking…" else "Connect") }
        Spacer(Modifier.height(10.dp))
        Text(
            "In Anya on the PC: Settings → Phone access shows this address and key (scan the QR there).",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
fun ChatScreen(url: String, key: String, onForget: () -> Unit) {
    val api = remember(url, key) { AnyaApi(url, key) }
    val messages = remember { mutableStateListOf<Msg>() }
    val listState = rememberLazyListState()
    var input by remember { mutableStateOf("") }
    var sending by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    var sessionId by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) listState.animateScrollToItem(messages.lastIndex)
    }

    Column(Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Anya", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
            TextButton(onClick = { messages.clear(); sessionId = null }) { Text("New") }
            TextButton(onClick = onForget) { Text("Disconnect") }
        }
        LazyColumn(
            state = listState,
            modifier = Modifier.weight(1f).fillMaxWidth().padding(horizontal = 12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(messages) { m -> Bubble(m) }
        }
        Row(
            modifier = Modifier.fillMaxWidth().padding(12.dp),
            verticalAlignment = Alignment.Bottom,
        ) {
            OutlinedTextField(
                value = input,
                onValueChange = { input = it },
                modifier = Modifier.weight(1f),
                placeholder = { Text("Message Anya…") },
                maxLines = 5,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = {
                    if (!sending && input.isNotBlank()) {
                        val text = input.trim()
                        input = ""
                        messages.add(Msg("you", text))
                        val reply = Msg("anya", "")
                        messages.add(reply)
                        sending = true
                        api.chat(sessionId, text,
                            onLine = { chunk -> reply.text += chunk },
                            onSession = { sessionId = it },
                            onDone = { _, _ -> sending = false },
                        )
                    }
                }),
            )
            Spacer(Modifier.width(8.dp))
            Button(
                onClick = {
                    if (!sending && input.isNotBlank()) {
                        val text = input.trim()
                        input = ""
                        messages.add(Msg("you", text))
                        val reply = Msg("anya", "")
                        messages.add(reply)
                        sending = true
                        api.chat(sessionId, text,
                            onLine = { chunk -> reply.text += chunk },
                            onSession = { sessionId = it },
                            onDone = { _, _ -> sending = false },
                        )
                    }
                },
                enabled = !sending,
            ) { Text(if (sending) "…" else "Send") }
        }
    }
}

@Composable
fun Bubble(m: Msg) {
    val mine = m.from == "you"
    val bg = if (mine) MaterialTheme.colorScheme.primaryContainer
             else MaterialTheme.colorScheme.surfaceVariant
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start,
    ) {
        Box(
            modifier = Modifier
                .widthIn(max = 320.dp)
                .background(bg, RoundedCornerShape(14.dp))
                .padding(horizontal = 12.dp, vertical = 9.dp),
        ) {
            Text(
                text = if (mine) m.text else (m.text.ifBlank { "…" }),
                fontFamily = if (!mine && m.text.contains("```")) FontFamily.Monospace else FontFamily.Default,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}
'''

_ANYA_API = r'''package com.anya.phone

import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/**
 * The whole client: health check plus one streaming chat call.
 *
 * Auth is the same shared key the web UI uses.  We always send it as the
 * `X-Anya-Key` header so the key never lands in a query string on the phone.
 */
class AnyaApi(private val base: String, private val key: String) {

    private fun open(path: String, method: String): HttpURLConnection {
        val c = URL(base + path).openConnection() as HttpURLConnection
        c.requestMethod = method
        c.connectTimeout = 8000
        c.readTimeout = 120000
        if (key.isNotBlank()) c.setRequestProperty("X-Anya-Key", key)
        return c
    }

    /** Cheap liveness check so the connect screen can say *why* it failed. */
    fun check(done: (Boolean, String) -> Unit) {
        thread {
            var ok = false
            var why = ""
            try {
                val c = open("/api/status", "GET")
                val code = c.responseCode
                if (code == 401 || code == 403) {
                    why = "The key was refused. Check the key in Phone access."
                } else if (code in 200..299) {
                    val body = c.inputStream.bufferedReader().use { it.readText() }
                    val j = JSONObject(body)
                    ok = true
                    if (!j.optBoolean("running", false)) why = "Connected, but her model is not loaded yet."
                } else {
                    why = "Server said HTTP $code."
                }
            } catch (e: Exception) {
                why = "Could not reach $base — ${e.message ?: "no connection"}"
            }
            android.os.Handler(android.os.Looper.getMainLooper()).post { done(ok, why) }
        }
    }

    /**
     * POST /api/chat and stream the SSE reply.
     *
     * Events arrive as `data: {json}` lines with a `type` field.  We append
     * `token` text, remember `start.session_id`, and stop at `done`/`error`.
     */
    fun chat(
        sessionId: String?,
        message: String,
        onLine: (String) -> Unit,
        onSession: (String) -> Unit,
        onDone: (Boolean, String) -> Unit,
    ) {
        thread {
            var ok = false
            var why = ""
            try {
                val c = open("/api/chat", "POST")
                c.doOutput = true
                c.setRequestProperty("Content-Type", "application/json")
                val payload = JSONObject()
                if (!sessionId.isNullOrBlank()) payload.put("session_id", sessionId)
                payload.put("message", message)
                c.outputStream.use { it.write(payload.toString().toByteArray()) }

                if (c.responseCode !in 200..299) {
                    why = "HTTP ${c.responseCode}"
                } else {
                    BufferedReader(InputStreamReader(c.inputStream)).use { r ->
                        while (true) {
                            val line = r.readLine() ?: break
                            if (!line.startsWith("data:")) continue
                            val raw = line.removePrefix("data:").trim()
                            if (raw.isEmpty()) continue
                            val j = JSONObject(raw)
                            when (j.optString("type")) {
                                "start" -> j.optString("session_id").takeIf { it.isNotBlank() }
                                    ?.let { id -> android.os.Handler(android.os.Looper.getMainLooper())
                                        .post { onSession(id) } }
                                "token" -> {
                                    val t = j.optString("text", "")
                                    if (t.isNotEmpty()) android.os.Handler(android.os.Looper.getMainLooper())
                                        .post { onLine(t) }
                                }
                                "done" -> ok = true
                                "error" -> why = j.optString("message", "unknown error")
                            }
                        }
                    }
                }
            } catch (e: Exception) {
                why = e.message ?: "connection lost"
            }
            android.os.Handler(android.os.Looper.getMainLooper()).post { onDone(ok, why) }
        }
    }
}
'''

_PREFS = r'''package com.anya.phone

import android.content.Context

/**
 * Remembers the server address and key between launches.
 *
 * `Prefs.current` is set once from `MainActivity.onCreate`, which keeps the
 * Compose screens free of Context plumbing.
 */
class Prefs(private val ctx: Context) {
    companion object {
        lateinit var current: Prefs
        fun install(ctx: Context) { current = Prefs(ctx) }
    }

    private val sp = ctx.getSharedPreferences("anya", Context.MODE_PRIVATE)

    val url: String get() = sp.getString("url", "") ?: ""
    val key: String get() = sp.getString("key", "") ?: ""

    fun save(url: String, key: String) {
        sp.edit().putString("url", url.trim().trimEnd('/')).putString("key", key.trim()).apply()
    }
}
'''

_MANIFEST = '''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:tools="http://schemas.android.com/tools">

    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />

    <application
        android:allowBackup="true"
        android:usesCleartextTraffic="true"
        android:label="@string/app_name"
        android:icon="@mipmap/ic_launcher"
        android:roundIcon="@mipmap/ic_launcher_round"
        android:supportsRtl="true"
        android:theme="@style/Theme.MyApplication">
        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:label="@string/app_name"
            android:theme="@style/Theme.MyApplication"
            android:windowSoftInputMode="adjustResize">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>

</manifest>
'''

_THEME_KT = r'''package com.anya.phone.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Anya's violet, matching her desktop accent.
private val Violet = Color(0xFF7C5CFF)
private val VioletLight = Color(0xFFA78BFA)
private val Dark = Color(0xFF0B0C10)
private val DarkPanel = Color(0xFF171A23)
private val Light = Color(0xFFF6F6F9)
private val LightPanel = Color(0xFFECEAF4)

private val DarkScheme = darkColorScheme(
    primary = Violet,
    onPrimary = Color.White,
    primaryContainer = Color(0xFF2E2350),
    onPrimaryContainer = Color(0xFFE3DBFF),
    secondary = VioletLight,
    background = Dark,
    onBackground = Color(0xFFE8EAF0),
    surface = DarkPanel,
    onSurface = Color(0xFFE8EAF0),
    surfaceVariant = Color(0xFF1E2230),
    onSurfaceVariant = Color(0xFFC9CEDA),
)

private val LightScheme = lightColorScheme(
    primary = Violet,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFE3DBFF),
    onPrimaryContainer = Color(0xFF221A45),
    secondary = Color(0xFF5B45C9),
    background = Light,
    onBackground = Color(0xFF14151A),
    surface = LightPanel,
    onSurface = Color(0xFF14151A),
    surfaceVariant = Color(0xFFDCD9E8),
    onSurfaceVariant = Color(0xFF3A3B45),
)

@Composable
fun AnyaTheme(darkTheme: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (darkTheme) DarkScheme else LightScheme, content = content)
}
'''

_STRINGS = '''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">Anya</string>
</resources>
'''

_ICON_FG = '''<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp" android:height="108dp"
    android:viewportWidth="108" android:viewportHeight="108">
    <path android:fillColor="#FFFFFF"
        android:pathData="M36,70 L44,38 L50,38 L58,70 L52.5,70 L50.6,62 L43.4,62 L41.5,70 Z M44.5,57.5 L49.5,57.5 L47,45.5 Z" />
    <path android:fillColor="#FFFFFF"
        android:pathData="M64,70 L64,38 L69.5,38 L69.5,70 Z M69.5,70 L69.5,64.5 L76,64.5 Z" />
</vector>
'''

_ADAPTIVE_ICON = '''<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_launcher_background" />
    <foreground android:drawable="@drawable/anya_mark" />
</adaptive-icon>
'''


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _sync_sources(dst: Path) -> None:
    """Write our Kotlin/manifest/assets over the scaffolded project."""
    pkg = dst / "app" / "src" / "main" / "java" / "com" / "anya" / "phone"
    _write(pkg / "MainActivity.kt", _MAIN_ACTIVITY)
    _write(pkg / "AnyaApi.kt", _ANYA_API)
    _write(pkg / "Prefs.kt", _PREFS)
    _write(pkg / "ui" / "theme" / "Theme.kt", _THEME_KT)

    main = dst / "app" / "src" / "main"
    _write(main / "AndroidManifest.xml", _MANIFEST)
    _write(main / "res" / "values" / "strings.xml", _STRINGS)
    _write(main / "res" / "drawable" / "anya_mark.xml", _ICON_FG)

    # drop the leftover Java-package scaffolding the template ships with
    stale = dst / "app" / "src" / "main" / "java" / "com" / "example"
    if stale.exists():
        shutil.rmtree(stale, ignore_errors=True)
    for extra in ("test", "androidTest"):
        d = dst / "app" / "src" / extra
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)


def _patch_gradle(dst: Path) -> None:
    """Trim the template's test dependencies and set the icon."""
    bg = dst / "app" / "build.gradle.kts"
    txt = bg.read_text(encoding="utf-8")
    txt = txt.replace('versionName = "1.0"', 'versionName = "0.17.0"')
    txt = txt.replace('versionCode = 1', 'versionCode = 1700')
    for line in ("testImplementation(libs.junit)",
                 "androidTestImplementation(platform(libs.androidx.compose.bom))",
                 "androidTestImplementation(libs.androidx.compose.ui.test.junit4)",
                 "androidTestImplementation(libs.androidx.espresso.core)",
                 "androidTestImplementation(libs.androidx.junit)",
                 "debugImplementation(libs.androidx.compose.ui.test.manifest)"):
        txt = txt.replace("    " + line + "\n", "")
    # release builds must not need a signing config we do not have
    bg.write_text(txt, encoding="utf-8")

    # the icon: reuse the desktop PNG for the legacy mipmaps.  The template
    # ships .webp files; writing .png alongside them is a *duplicate resource*
    # error, so remove the template's copies and add ours instead.
    if _ICON_PNG.exists():
        data = _ICON_PNG.read_bytes()
        res = dst / "app" / "src" / "main" / "res"
        for d in main_mipmaps(dst):
            for base in ("ic_launcher", "ic_launcher_round"):
                for stale in d.glob(base + ".*"):
                    stale.unlink()
                _write_png(d / (base + ".png"), data)
        # adaptive icon: a solid background with her mark in front
        anydpi = res / "mipmap-anydpi-v26"
        anydpi.mkdir(parents=True, exist_ok=True)
        _write(anydpi / "ic_launcher.xml", _ADAPTIVE_ICON)
        _write(anydpi / "ic_launcher_round.xml", _ADAPTIVE_ICON)
        _write(res / "values" / "ic_launcher_background.xml",
               '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
               '    <color name="ic_launcher_background">#0B0C10</color>\n'
               '</resources>\n')


def main_mipmaps(dst: Path) -> list[Path]:
    res = dst / "app" / "src" / "main" / "res"
    return [res / n for n in ("mipmap-mdpi", "mipmap-hdpi", "mipmap-xhdpi",
                              "mipmap-xxhdpi", "mipmap-xxxhdpi")]


def _write_png(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


# --- public API -------------------------------------------------------------

def exists() -> bool:
    return (app_dir() / "gradlew.bat").exists()


def ensure(key: str = "") -> Path:
    """Create the phone-app project if it isn't there yet; return its folder."""
    if exists():
        return app_dir()
    template = projects._TEMPLATES / projects.ANDROID_KIND
    if not template.exists():
        raise ProjectError(
            "no Android template to build from - expected "
            f"{template}")
    # start from the template ourselves rather than new_project(), so the folder
    # id is exactly PROJECT_ID instead of a slug of the display name
    dst = app_dir()
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    ignore = shutil.ignore_patterns("build", ".gradle", ".idea", ".git",
                                    "local.properties")
    shutil.copytree(template, dst, ignore=ignore, dirs_exist_ok=False)
    _patch_android(dst)
    sdk = projects.find_sdk()
    if sdk:
        _write(dst / "local.properties",
               "sdk.dir=" + str(sdk).replace("\\", "\\\\") + "\n")

    now = time.time()
    proj = {
        "id": PROJECT_ID, "name": APP_NAME, "kind": projects.ANDROID_KIND,
        "description": "Anya's own Android chat client",
        "created": now, "updated": now, "status": "active",
        "tasks": [{"id": "t1", "title": "Build the phone app", "status": "doing",
                   "created": now, "updated": now}],
        "log": [{"ts": now, "kind": "note",
                 "text": "Created Anya's phone app from the Android template"}],
        "last_build": {},
    }
    projects._save(PROJECT_ID, proj)

    _sync_sources(dst)
    _patch_gradle(dst)
    return dst


PKG = "com.anya.phone"


def _patch_android(dst: Path) -> None:
    """Set the app id, package and name, then move the sources to our package.

    This is deliberately separate from `projects._patch_android`, which derives
    the package from the project id — here the package is fixed (`PKG`), so the
    Kotlin sources we write always line up.
    """
    sg = dst / "settings.gradle.kts"
    if sg.exists():
        sg.write_text(re.sub(r'rootProject\.name\s*=\s*"[^"]*"',
                             'rootProject.name = "anya-phone"',
                             sg.read_text(encoding="utf-8")), encoding="utf-8")

    bg = dst / "app" / "build.gradle.kts"
    if bg.exists():
        txt = bg.read_text(encoding="utf-8")
        txt = re.sub(r'namespace\s*=\s*"[^"]*"', f'namespace = "{PKG}"', txt)
        txt = re.sub(r'applicationId\s*=\s*"[^"]*"', f'applicationId = "{PKG}"', txt)
        bg.write_text(txt, encoding="utf-8")

    strings = dst / "app" / "src" / "main" / "res" / "values" / "strings.xml"
    if strings.exists():
        strings.write_text(
            re.sub(r"<string name=\"app_name\">.*?</string>",
                   f'<string name="app_name">{APP_NAME}</string>',
                   strings.read_text(encoding="utf-8")), encoding="utf-8")

    # move the template's Kotlin sources into our own package folder, then
    # rewrite the package line inside each file
    src_root = dst / "app" / "src" / "main" / "java"
    old = src_root / "com" / "example" / "myapplication"
    new = src_root / Path(*PKG.split("."))
    if old.exists():
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old), str(new))
    for kt in (dst / "app" / "src").rglob("*.kt"):
        txt = kt.read_text(encoding="utf-8").replace(
            "com.example.myapplication", PKG)
        kt.write_text(txt, encoding="utf-8")


INDEX_NAME = "anya-phone.apk"


def _apk_out_dir() -> Path:
    return Path(projects._STATE_DIR or Path.cwd()) / "phone"


def published_apk() -> Path | None:
    """The APK we hand to the phone, if it was built this session."""
    p = _apk_out_dir() / INDEX_NAME
    return p if p.exists() else None


def publish(src_apk: Path) -> Path:
    """Copy a freshly built APK next to the app so it can be served."""
    out = _apk_out_dir() / INDEX_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_apk, out)
    return out


def build(on_line=None, key: str = "") -> dict:
    """Create-then-build the phone app, publishing the APK for download."""
    ensure(key)
    res = projects.build_apk(PROJECT_ID, on_line=on_line)
    apk = (res.get("apk") or {})
    src = apk.get("path", "")
    out = {"ok": False, "code": res.get("code"), "output": res.get("output", ""),
           "duration_s": res.get("duration_s"), "name": apk.get("name", ""),
           "bytes": apk.get("bytes", 0), "apk": "", "ts": time.time()}
    if src and Path(src).exists():
        dest = publish(Path(src))
        out["ok"] = bool(res.get("ok"))
        out["apk"] = str(dest)
    return out


def status(key: str = "") -> dict:
    """Everything the GUI needs to render the Phone app section."""
    apk = published_apk()
    src: dict = {}
    if exists():
        try:
            src = projects._find_apk(PROJECT_ID) or {}
        except Exception:                                         # noqa: BLE001
            src = {}
    return {
        "exists": exists(),
        "project": PROJECT_ID,
        "name": APP_NAME,
        "apk": str(apk) if apk else "",
        "apk_bytes": apk.stat().st_size if apk else int(src.get("bytes") or 0),
        "built": src.get("built"),
        "key_set": bool(key),
        "download_path": "/anya-phone.apk",
    }
