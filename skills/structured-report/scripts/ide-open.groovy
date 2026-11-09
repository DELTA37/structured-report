// structured-report → JetBrains IDE: show a session's report next to the session, as a split  Session | Report.
//
// Run inside a running PyCharm / WebStorm by the IDE's own `ideScript` command (ide.py does it):
//   /Applications/WebStorm.app/Contents/MacOS/webstorm ideScript <this file>
// It takes every request ~/.claude/structured-report/ide/requests/<sid>.properties  (project, html, title, sid; UTF-8)
// whose project is open in THIS IDE, opens the HTML in the IDE's built-in browser (JCEF) in the editor
// window to the right of the current one (splitting the window if there is no right one), and reloads it
// whenever the HTML file changes. A request for a project this IDE does not have is left for the other IDE.
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.fileEditor.ex.FileEditorManagerEx
import com.intellij.openapi.fileEditor.impl.EditorWindow
import com.intellij.openapi.fileEditor.impl.HTMLEditorProvider
import com.intellij.openapi.project.ProjectManager
import javax.swing.SwingConstants

def home = System.getProperty("user.home") + "/.claude/structured-report/ide"
def logf = new File(home, "ide.log")
def log = { String m -> logf << "${java.time.LocalDateTime.now().withNano(0)} ${m}\n" }
def reqDir = new File(home, "requests")
def reqs = (reqDir.listFiles() ?: []).findAll { it.name.endsWith(".properties") }

def projectFor = { String path ->
    ProjectManager.instance.openProjects.findAll { p -> p.basePath && (path == p.basePath || path.startsWith(p.basePath + "/")) }
            .max { it.basePath.length() }
}

def findBrowser
findBrowser = { Object o, int depth ->            // the JCEF browser behind an HTML editor (for reload)
    if (o == null || depth > 4) return null
    if (o.getClass().name.contains("JBCefBrowser")) {
        if (o.metaClass.respondsTo(o, "getCefBrowser")) return o
        def f = o.getClass().declaredFields.find { it.type.name.contains("JBCefBrowser") }   // JBCefBrowser$MyPanel → its browser
        if (f) { f.accessible = true; return f.get(o) }
    }
    if (o instanceof java.awt.Container) {
        for (c in o.components) { def b = findBrowser(c, depth + 1); if (b) return b }
    }
    return null
}

// Reload the report tab whenever its HTML is rebuilt; one watcher per tab, ends with the tab.
// Each run of this script restarts all watchers, so a new version of the script takes over at once.
def KEY = "structured-report.watch."
def watch = { project, fem, File html, String title, String sid ->
    def key = KEY + title
    if (System.getProperty(key + ".alive")) return
    System.setProperty(key, project.basePath + "\n" + html.path + "\n" + sid)
    System.setProperty(key + ".alive", "1")
    Thread.start("structured-report-reload-" + sid) {
        def last = html.lastModified()
        def gone = 0
        try {
            while (!project.disposed && gone < 3) {
                sleep(1500)
                def tab = null
                ApplicationManager.application.invokeAndWait {
                    tab = fem.windows.collectMany { w -> w.files.toList() }.find { it.name == title }
                }
                gone = tab ? 0 : gone + 1
                def m = html.lastModified()
                if (tab && m != last) {
                    last = m
                    sleep(300)                              // let build.py finish writing
                    ApplicationManager.application.invokeLater {
                        try {
                            def b = findBrowser(fem.getSelectedEditor(tab)?.component, 0)
                            if (b) b.cefBrowser.reloadIgnoreCache() else log("${sid}: no browser to reload")
                        } catch (Throwable t) { log("${sid}: reload failed: ${t}") }
                    }
                }
            }
            if (gone >= 3) System.clearProperty(key)        // tab closed: forget it
        } catch (InterruptedException ignored) {
        } catch (Throwable t) {
            log("${sid}: watcher stopped: ${t}")
        } finally {
            System.clearProperty(key + ".alive")
        }
    }
}

// restart: stop old watchers (possibly older code), start fresh ones for every tab still open
Thread.getAllStackTraces().keySet().findAll { it.name.startsWith("structured-report-reload-") }*.interrupt()
sleep(200)
System.properties.stringPropertyNames().findAll { it.startsWith(KEY) }.each { System.clearProperty(it + ".alive") }
System.properties.stringPropertyNames().findAll { it.startsWith(KEY) && !it.endsWith(".alive") }.each { k ->
    def parts = System.getProperty(k).split("\n").toList()
    if (parts.size() != 3) { System.clearProperty(k); return }      // left by an older version
    def (base, path, sid) = parts
    def project = ProjectManager.instance.openProjects.find { it.basePath == base }
    if (project) watch(project, FileEditorManagerEx.getInstanceEx(project), new File(path), k.substring(KEY.length()), sid)
}

reqs.each { File rf ->
    def r
    try { r = new Properties(); rf.withReader('UTF-8') { r.load(it) } } catch (e) { rf.delete(); return }
    def project = projectFor(r.project as String)
    if (!project) return                                   // another IDE's project
    rf.delete()
    def html = new File(r.html as String)
    def title = r.title as String
    ApplicationManager.application.invokeLater {
        try {
            def fem = FileEditorManagerEx.getInstanceEx(project)
            def open = fem.windows.find { w -> w.files.any { it.name == title } }
            if (open) {                                     // already shown: just bring it forward
                def f = open.files.find { it.name == title }
                fem.openFile(f, open, new com.intellij.openapi.fileEditor.impl.FileEditorOpenOptions().withRequestFocus(false))
                watch(project, fem, html, title, r.sid as String)
                log("${r.sid}: already open in ${project.name}")
                return
            }
            def cur = fem.currentWindow
            def right = cur?.adjacentEditors?.get(EditorWindow.RelativePosition.RIGHT)
            HTMLEditorProvider.getField("Companion").get(null).openEditor(project, title,
                    HTMLEditorProvider.Request.url(html.toURI().toString()))
            def file = fem.windows.collectMany { w -> w.files.toList() }.find { it.name == title }
            def home0 = fem.windows.find { w -> w.files.any { it.name == title } }
            if (file && home0) {
                if (right) {
                    fem.openFile(file, right, new com.intellij.openapi.fileEditor.impl.FileEditorOpenOptions().withRequestFocus(false))
                } else {
                    home0.split(SwingConstants.VERTICAL, true, file, false, true, true)
                }
                home0.closeFile(file, false)
                if (cur) cur.setAsCurrentWindow(true)       // focus stays on the session
            }
            watch(project, fem, html, title, r.sid as String)
            log("${r.sid}: opened in ${project.name} (${right ? 'right window' : 'new split'})")
        } catch (Throwable t) {
            log("${r.sid}: ERROR ${t}")
        }
    }
}
