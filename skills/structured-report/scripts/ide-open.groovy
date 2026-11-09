// structured-report → JetBrains IDE: the report of the ACTIVE agent session, beside it — a split  Session | Report.
//
// Run inside a running PyCharm / WebStorm by the IDE's own `ideScript` command (ide.py does it):
//   /Applications/WebStorm.app/Contents/MacOS/webstorm ideScript <this file>
//
// It installs (or replaces, when this script's VERSION changes) a small live service in every project that
// asked for it (requests ~/.claude/structured-report/ide/requests/*.properties from the SessionStart hook)
// or already shows a report. Every 1.5 s the service looks at the selected agent session tab
// (JetBrains Air: AgentThreadViewVirtualFile.sessionId) and:
//   • session has no prompt yet (its start screen)  → no report tab;
//   • session has a report with prompts             → one tab «Отчёт», in the editor window right of the
//     session (split once), shows THAT session's report; switching sessions switches the report;
//   • the shown report's HTML was rebuilt           → reload.
// The page runs in a windowed (not off-screen) JCEF browser: native mouse input — clicks, scrolling, dragging.
import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.fileEditor.ex.FileEditorManagerEx
import com.intellij.openapi.fileEditor.impl.EditorWindow
import com.intellij.openapi.fileEditor.impl.FileEditorOpenOptions
import com.intellij.openapi.fileEditor.impl.HTMLEditorProvider
import com.intellij.openapi.project.Project
import com.intellij.openapi.project.ProjectManager
import com.intellij.openapi.util.Disposer
import javax.swing.SwingConstants

final String TITLE = "Отчёт"
final String VERSION = "5"
def home = System.getProperty("user.home")
def dir = new File(home, ".claude/structured-report/ide")
def sessionsFile = new File(home, ".claude/structured-report/sessions.json")
def logf = new File(dir, "ide.log")
def log = { String m -> logf << "${java.time.LocalDateTime.now().withNano(0)} ${m}\n" }
def props = System.getProperties()                      // a Hashtable: survives between runs of this script

def sessionOf = { file ->                               // Air session tab → Claude session id
    if (file == null || !file.getClass().name.contains("AgentThreadView")) return null
    try { def f = file.getClass().getDeclaredField("sessionId"); f.accessible = true; return f.get(file) as String }
    catch (Throwable ignored) { return null }
}

def reportOf = { String sid ->                          // session → [html, hasPrompt]  (no JSON lib in the IDE's Groovy)
    if (!sid || !sessionsFile.exists()) return null
    def m = (sessionsFile.getText("UTF-8") =~ /"${java.util.regex.Pattern.quote(sid)}"\s*:\s*\{[^}]*?"report"\s*:\s*"([^"]+)"/)
    if (!m.find()) return null
    def base = m.group(1).replaceAll(/\.json$/, "")
    def html = new File(base + ".html"), journal = new File(base + ".journal.json")
    if (!html.exists()) return null
    return [html, journal.exists() && journal.getText("UTF-8").contains('"kind": "prompt"')]
}

def paneFile = { FileEditorManagerEx fem -> fem.windows.collectMany { it.files.toList() }.find { it.name == TITLE } }

def closePane = { FileEditorManagerEx fem, st ->
    fem.windows.each { w -> w.files.findAll { it.name == TITLE }.each { f -> w.closeFile(f, false) } }
    st.browser = null; st.html = null
}

// a tab «Отчёт» right of the session, with our own windowed browser inside
def openPane = { Project project, FileEditorManagerEx fem, st, File html ->
    def cur = fem.currentWindow
    def right = cur?.adjacentEditors?.get(EditorWindow.RelativePosition.RIGHT)
    def provider = HTMLEditorProvider.getField("Companion").get(null)
    provider.openEditor(project, TITLE, HTMLEditorProvider.Request.url(html.toURI().toString()))
    def file = paneFile(fem)
    def where = fem.windows.find { w -> w.files.any { it.name == TITLE } }
    if (!file || !where) return
    if (where.is(cur)) {                                // opened beside the session — move it to the right
        if (right) fem.openFile(file, right, new FileEditorOpenOptions().withRequestFocus(false))
        else where.split(SwingConstants.VERTICAL, true, file, false, true, true)
        where.closeFile(file, false)
        cur.setAsCurrentWindow(true)                    // focus stays on the session
    }
    st.html = html; st.mtime = html.lastModified(); st.browser = null
}

def findBrowser
findBrowser = { Object o, int depth ->                  // the JCEF browser behind the HTML editor
    if (o == null || depth > 5) return null
    if (o.getClass().name.contains("JBCefBrowser")) {
        if (o.metaClass.respondsTo(o, "getCefBrowser")) return o
        def f = o.getClass().declaredFields.find { it.type.name.contains("JBCefBrowser") }   // JBCefBrowser$MyPanel
        if (f) { f.accessible = true; return f.get(o) }
    }
    if (o instanceof java.awt.Container) for (c in o.components) { def b = findBrowser(c, depth + 1); if (b) return b }
    return null
}

def DEBUG_JS = new File(dir, "debug.js")                // temporary: log mouse events of the page into ide.log
def debugHook = { b ->
    if (!DEBUG_JS.exists() || b == null) return
    if (!b.metaClass.hasProperty(b, "srDebug")) {
        def cl = b.cefBrowser.getClass().classLoader
        def iface = cl.loadClass("org.cef.handler.CefDisplayHandler")
        def h = java.lang.reflect.Proxy.newProxyInstance(cl, [iface] as Class[], { proxy, m, args ->
            if (m.name == "onConsoleMessage" && String.valueOf(args[2]).startsWith("SREV")) log(String.valueOf(args[2]))
            if (m.returnType == boolean.class) return false
            return null } as java.lang.reflect.InvocationHandler)
        b.JBCefClient.addDisplayHandler(h, b.cefBrowser)
        b.metaClass.srDebug = true
    }
    b.cefBrowser.executeJavaScript(DEBUG_JS.text, b.cefBrowser.URL, 0)
}

def tick = { Project project, st ->
    def fem = FileEditorManagerEx.getInstanceEx(project)
    def pane = paneFile(fem)
    if (!pane) { st.browser = null; st.html = null }
    def sel = ([fem.currentWindow] + fem.windows.toList()).findResult { w -> w?.selectedFile && sessionOf(w.selectedFile) ? w.selectedFile : null }
    def sid = sessionOf(sel)
    if (!sid) return                                    // looking at code, not at a session: leave the pane alone
    def rep = reportOf(sid)
    if (!rep || !rep[1]) { if (pane) closePane(fem, st); return }     // start screen / no report: no pane
    File html = rep[0]
    if (!pane) { openPane(project, fem, st, html); return }
    if (!st.browser) { st.browser = findBrowser(fem.getSelectedEditor(pane)?.component, 0); if (!st.browser) return }
    debugHook(st.browser)
    if (st.html != html) { st.browser.loadURL(html.toURI().toString()); st.html = html; st.mtime = html.lastModified(); return }
    if (html.lastModified() != st.mtime) { st.mtime = html.lastModified(); st.browser.cefBrowser.reloadIgnoreCache() }
}

def install = { Project project ->
    def key = "structured-report.pane." + project.locationHash
    def old = props.get(key)
    if (old instanceof Map && old.version == VERSION && !Disposer.isDisposed(old.disposable)) return
    if (old instanceof Map) Disposer.dispose(old.disposable)
    Disposable d = Disposer.newDisposable("structured-report pane")
    Disposer.register(project, d)
    def st = [version: VERSION, disposable: d, browser: null, html: null, mtime: 0L]
    props.put(key, st)
    Disposer.register(d, { props.remove(key) } as Disposable)
    closePane(FileEditorManagerEx.getInstanceEx(project), st)        // a pane of an older version
    Thread.start("structured-report-pane-" + project.name) {
        while (!Disposer.isDisposed(d) && !project.disposed) {
            try {
                sleep(1500)
                ApplicationManager.application.invokeAndWait {
                    try { if (!Disposer.isDisposed(d)) tick(project, st) }
                    catch (Throwable t) { log("${project.name}: ${t}") }
                }
            } catch (InterruptedException ignored) { break }
            catch (Throwable t) { if (t.getClass().name.contains("Cancel")) break; log("${project.name}: ${t}") }
        }
    }
    log("${project.name}: report pane service v${VERSION} on")
}

def projectFor = { String path ->
    ProjectManager.instance.openProjects.findAll { p -> p.basePath && (path == p.basePath || path.startsWith(p.basePath + "/")) }
            .max { it.basePath.length() }
}

// requests from the SessionStart hook: which projects want the service
def wanted = [] as Set
(new File(dir, "requests").listFiles() ?: []).findAll { it.name.endsWith(".properties") }.each { File rf ->
    def r = new Properties()
    try { rf.withReader("UTF-8") { r.load(it) } } catch (e) { rf.delete(); return }
    def project = projectFor(r.project as String)
    if (!project) return                                // another IDE's project
    rf.delete()
    wanted << project
}

// leftovers of v1/v2: their watcher threads
Thread.getAllStackTraces().keySet().findAll { it.name.startsWith("structured-report-reload-") }*.interrupt()

ApplicationManager.application.invokeLater {
    ProjectManager.instance.openProjects.each { p ->
        try {
            def fem = FileEditorManagerEx.getInstanceEx(p)
            fem.windows.each { w -> w.files.findAll { it.name.startsWith(TITLE + " · ") }.each { f -> w.closeFile(f, false) } }
            def running = props.get("structured-report.pane." + p.locationHash)
            if (p in wanted || running || paneFile(fem)) install(p)
        } catch (Throwable t) {
            log("${p.name}: ERROR ${t}")
        }
    }
}
