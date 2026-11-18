# Invoke the Installed apps entry on an English-language Windows test host
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$scope = [System.Windows.Automation.TreeScope]::Descendants
$all = [System.Windows.Automation.Condition]::TrueCondition
$invoke = [System.Windows.Automation.InvokePattern]::Pattern

function Wait-SettingsControl($description, [scriptblock]$select) {
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        $ids = @(Get-Process SystemSettings -ErrorAction SilentlyContinue).Id
        $controls = @([System.Windows.Automation.AutomationElement]::RootElement.FindAll($scope, $all) |
            Where-Object { $ids -contains $_.Current.ProcessId })
        $match = @(& $select $controls)
        if ($match.Count -eq 1) { return $match[0] }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    $controls | Where-Object { $_.Current.Name -match 'Entropy|Uninstall|Remove' } | ForEach-Object {
        Write-Host $_.Current.ControlType.ProgrammaticName $_.Current.AutomationId $_.Current.Name
    }
    throw "Windows Settings did not expose a unique $description"
}

Start-Process 'ms-settings:appsfeatures'
$options = Wait-SettingsControl 'menu for the Entropy entry' {
    param($controls)
    $row = $controls | Where-Object {
        $_.Current.ControlType.ProgrammaticName -eq 'ControlType.ListItem' -and
        $_.Current.Name -match '^Entropy, [^,]+, jedace07,'
    }
    if (@($row).Count -eq 1) {
        $row.FindAll($scope, $all) | Where-Object {
            $_.Current.AutomationId -eq 'AppOptionsButton' -and
            $_.Current.IsEnabled
        }
    }
}
$options.GetCurrentPattern($invoke).Invoke()
foreach ($type in 'MenuItem', 'Button') {
    $uninstall = Wait-SettingsControl "Uninstall $type" {
        param($controls)
        $controls | Where-Object {
            $_.Current.ControlType.ProgrammaticName -eq "ControlType.$type" -and
            $_.Current.Name -eq 'Uninstall' -and $_.Current.IsEnabled
        }
    }
    $uninstall.GetCurrentPattern($invoke).Invoke()
}
