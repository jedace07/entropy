function Component() {}

Component.prototype.createOperations = function() {
    component.createOperations();
    component.addOperation("CreateShortcut", "@TargetDir@/app/Entropy.exe",
        "@StartMenuDir@/Entropy.lnk", "workingDirectory=@TargetDir@/app",
        "iconPath=@TargetDir@/app/Entropy.ico", "description=Entropy image upscaler");
    component.addOperation("CreateShortcut", "@TargetDir@/app/Entropy.exe",
        "@DesktopDir@/Entropy.lnk", "workingDirectory=@TargetDir@/app",
        "iconPath=@TargetDir@/app/Entropy.ico", "description=Entropy image upscaler");
    // Start search hides shortcuts matching the registered UninstallString, so
    // add a flag that has no effect on uninstall to keep this one listed
    component.addOperation("CreateShortcut", "@TargetDir@/EntropyMaintenanceTool.exe",
        "@StartMenuDir@/Uninstall Entropy.lnk", "--start-uninstaller --no-size-checking",
        "workingDirectory=@TargetDir@", "description=Uninstall Entropy");
};
