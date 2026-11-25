ObjC.import("AppKit");
ObjC.bindFunction("kill", ["int", ["int", "int"]]);

function processIsRunning(pid) {
    return pid > 0 && Number($.kill(pid, 0)) === 0;
}

function runningFork() {
    const apps = $.NSRunningApplication.runningApplicationsWithBundleIdentifier("com.DanPristupov.Fork");
    for (let index = 0; index < Number(apps.count); index++) {
        const app = apps.objectAtIndex(index);
        if (processIsRunning(Number(app.processIdentifier))) {
            return app;
        }
    }
    return null;
}

function run() {
    const fork = runningFork();
    if (!fork) {
        return;
    }

    const pid = Number(fork.processIdentifier);
    const bundlePath = ObjC.unwrap(fork.bundleURL.path);
    if (!bundlePath) {
        return;
    }

    const application = $.NSApplication.sharedApplication;
    application.setActivationPolicy(Number($.NSApplicationActivationPolicyAccessory));
    application.activateIgnoringOtherApps(true);

    const alert = $.NSAlert.alloc.init;
    alert.messageText = "XBotGo 已更新";
    alert.informativeText = "要现在重启 Fork 以加载更新后的自定义命令吗？";
    alert.addButtonWithTitle("重启 Fork");
    const later = alert.addButtonWithTitle("稍后");
    later.keyEquivalent = "\u001b";
    if (Number(alert.runModal) !== Number($.NSAlertFirstButtonReturn)) {
        return;
    }

    if (processIsRunning(pid) && !fork.terminate) {
        return;
    }

    const deadline = $.NSDate.dateWithTimeIntervalSinceNow(30);
    while (processIsRunning(pid) && deadline.timeIntervalSinceNow > 0) {
        $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(0.2));
    }
    if (processIsRunning(pid) || runningFork()) {
        return;
    }

    const open = $.NSTask.alloc.init;
    open.setLaunchPath("/usr/bin/open");
    open.setArguments($(["-a", bundlePath]));
    open.launch;
    open.waitUntilExit;
}
