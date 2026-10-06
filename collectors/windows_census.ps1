# Windows Server 2019/2022 census. Read-only queries; one structured output object.
# Deliberately omits command lines, service paths, task arguments, and credentials.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')]
    [string]$InventoryId,
    [bool]$IncludeRoleMetadata = $false
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$WarningPreference = 'SilentlyContinue'
$VerbosePreference = 'SilentlyContinue'
if (Get-Variable -Name Ansible -ErrorAction SilentlyContinue) {
    $Ansible.Changed = $false
}
$script:CensusSections = [ordered]@{}

function Invoke-CensusSection {
    param(
        [string]$Name,
        [string[]]$Commands = @(),
        [scriptblock]$Query,
        [switch]$ArrayData,
        [bool]$Enabled = $true
    )
    if (-not $Enabled) {
        $script:CensusSections[$Name] = [ordered]@{
            status = 'skipped'; reason = 'optional_collection_disabled'
        }
        return
    }
    $missing = @($Commands | Where-Object {
        -not (Get-Command -Name $_ -ErrorAction SilentlyContinue)
    })
    if ($missing.Count -gt 0) {
        $script:CensusSections[$Name] = [ordered]@{
            status = 'not_installed'; reason = 'commands_unavailable'; commands = $missing
        }
        return
    }
    try {
        if ($ArrayData) { $data = @(& $Query) }
        else { $data = & $Query }
        $script:CensusSections[$Name] = [ordered]@{ status = 'ok'; data = $data }
    }
    catch {
        # Raw error messages can contain user-controlled strings or credentials.
        # Keep only a status and an exception type, never Exception.Message.
        $cimStatus = $_.Exception.PSObject.Properties['StatusCode']
        $denied = $_.CategoryInfo.Category -eq 'PermissionDenied' -or
            $_.Exception -is [System.UnauthorizedAccessException] -or
            $_.Exception.HResult -eq -2147024891 -or
            $_.Exception.HResult -eq -2147217405 -or
            ($null -ne $cimStatus -and [string]$cimStatus.Value -eq 'AccessDenied') -or
            $_.FullyQualifiedErrorId -match 'AccessDenied|UnauthorizedAccess|PermissionDenied'
        $script:CensusSections[$Name] = [ordered]@{
            status = $(if ($denied) { 'access_denied' } else { 'error' })
            reason = $(if ($denied) { 'query_permission_denied' } else { 'query_failed' })
            exception_type = $_.Exception.GetType().FullName
        }
    }
}

function Get-SafeProcessName {
    param([uint32]$ProcessId)
    # A process can exit between socket enumeration and this lookup.
    $processInfo = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($processInfo) { return [string]$processInfo.ProcessName }
    return $null
}

function Get-SafeMountSource {
    param([AllowNull()][string]$Value)
    if ($null -eq $Value) { return $null }
    if ($Value.Length -gt 4096 -or $Value -match '[\x00-\x1f\x7f]') {
        return '[omitted: unsafe source]'
    }
    if ($Value -match '(?i)(password|passwd|pass|credentials?|token|secret|api[_-]?key|access[_-]?key|username|user)\s*=') {
        return '[omitted: credential-bearing source]'
    }
    $safe = ($Value -split '[?#]', 2)[0]
    # Only source identities are retained; no URI userinfo or credential options.
    $match = [regex]::Match($safe, '^(?<prefix>[A-Za-z][A-Za-z0-9+.-]*://|//|\\\\)(?<authority>[^/\\]*)(?<path>.*)$')
    if ($match.Success) {
        $authority = ($match.Groups['authority'].Value -split '@')[-1]
        if ($authority -notmatch '^(?:[A-Za-z0-9_.-]+|\[[A-Za-z0-9:.%_-]+\])(?::\d+)?$') {
            return '[omitted: unsafe source]'
        }
        return $match.Groups['prefix'].Value + $authority + $match.Groups['path'].Value
    }
    if ($safe -match '@') { return '[omitted: unsafe source]' }
    return $safe
}

Invoke-CensusSection -Name identity -Commands Get-CimInstance -Query {
    $system = Get-CimInstance -ClassName Win32_ComputerSystem
    $os = Get-CimInstance -ClassName Win32_OperatingSystem
    $bios = Get-CimInstance -ClassName Win32_BIOS
    $processors = @(Get-CimInstance -ClassName Win32_Processor | ForEach-Object {
        [ordered]@{
            name = [string]$_.Name
            cores = [int]$_.NumberOfCores
            logical_processors = [int]$_.NumberOfLogicalProcessors
        }
    })
    [ordered]@{
        hostname = [string]$system.Name
        dns_hostname = [string]$system.DNSHostName
        domain = [string]$system.Domain
        part_of_domain = [bool]$system.PartOfDomain
        domain_role = [int]$system.DomainRole
        os_name = [string]$os.Caption
        os_version = [string]$os.Version
        os_build = [string]$os.BuildNumber
        architecture = [string]$os.OSArchitecture
        last_boot_utc = $os.LastBootUpTime.ToUniversalTime().ToString('o')
        manufacturer = [string]$system.Manufacturer
        model = [string]$system.Model
        total_memory_bytes = [uint64]$system.TotalPhysicalMemory
        bios_version = [string]$bios.SMBIOSBIOSVersion
        processors = $processors
    }
}

Invoke-CensusSection -Name uptime -Commands Get-CimInstance -Query {
    $os = Get-CimInstance -ClassName Win32_OperatingSystem -OperationTimeoutSec 8
    if ($null -eq $os.LastBootUpTime) { throw 'boot_time_unavailable' }
    $bootTime = $os.LastBootUpTime.ToUniversalTime()
    $elapsed = ([DateTime]::UtcNow - $bootTime).TotalSeconds
    if ($elapsed -lt 0) { throw 'boot_time_in_future' }
    [ordered]@{
        uptime_seconds = $elapsed
        boot_time = $bootTime.ToString('o')
    }
}

Invoke-CensusSection -Name memory -Commands Get-CimInstance -Query {
    $os = Get-CimInstance -ClassName Win32_OperatingSystem -OperationTimeoutSec 8
    foreach ($name in @('TotalVisibleMemorySize', 'FreePhysicalMemory',
        'SizeStoredInPagingFiles', 'FreeSpaceInPagingFiles')) {
        if ($null -eq $os.$name) { throw 'memory_counter_unavailable' }
    }
    [ordered]@{
        total_bytes = [uint64]$os.TotalVisibleMemorySize * 1024
        available_bytes = [uint64]$os.FreePhysicalMemory * 1024
        swap_total_bytes = [uint64]$os.SizeStoredInPagingFiles * 1024
        swap_free_bytes = [uint64]$os.FreeSpaceInPagingFiles * 1024
    }
}

Invoke-CensusSection -Name hotfixes -Commands Get-HotFix -ArrayData -Query {
    # Win32_QuickFixEngineering is a limited inventory, not update compliance.
    Get-HotFix | ForEach-Object {
        $installed = $null
        try {
            if ($_.InstalledOn) { $installed = ([DateTime]$_.InstalledOn).ToString('yyyy-MM-dd') }
        }
        catch { $installed = $null }
        [ordered]@{ id = [string]$_.HotFixID; installed_at = $installed }
    }
}

Invoke-CensusSection -Name reboot_pending -Commands Test-Path, Get-ItemProperty -Query {
    $indicators = @()
    $keys = [ordered]@{
        component_based_servicing = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'
        windows_update = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
    }
    foreach ($name in $keys.Keys) {
        if (Test-Path -LiteralPath $keys[$name] -ErrorAction Stop) { $indicators += $name }
    }
    $sessionManager = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager'
    if (Test-Path -LiteralPath $sessionManager -ErrorAction Stop) {
        $state = Get-ItemProperty -LiteralPath $sessionManager -ErrorAction Stop
        foreach ($name in @('PendingFileRenameOperations', 'PendingFileRenameOperations2')) {
            if ($state.PSObject.Properties[$name] -and
                @($state.$name | Where-Object { $null -ne $_ -and [string]$_ -ne '' }).Count -gt 0) {
                $indicators += $name
            }
        }
    }
    # Values/paths are omitted: only indicator names leave the local registry.
    [ordered]@{ pending = [bool]($indicators.Count -gt 0); indicators = $indicators }
}

Invoke-CensusSection -Name smb_mappings -Commands Get-SmbMapping -ArrayData -Query {
    Get-SmbMapping | ForEach-Object {
        [ordered]@{
            local_path = [string]$_.LocalPath
            remote_path = Get-SafeMountSource -Value $_.RemotePath
            status = [string]$_.Status
        }
    }
}
$script:CensusSections['smb_mappings']['scope'] = 'current collection session; not all users; no reachability probe'

Invoke-CensusSection -Name configured_mounts -Commands Test-Path, Get-ChildItem, Get-ItemProperty -Query {
    $rows = @()
    if (Test-Path -LiteralPath 'HKCU:\Network' -ErrorAction Stop) {
        # The collection account's persisted drive mappings, including inactive ones.
        $rows = @(Get-ChildItem -LiteralPath 'HKCU:\Network' -ErrorAction Stop | ForEach-Object {
            if ($_.PSChildName -notmatch '^[A-Za-z]$') { return }
            $mapping = Get-ItemProperty -LiteralPath $_.PSPath -Name RemotePath -ErrorAction Stop
            [ordered]@{
                target = ([string]$_.PSChildName).ToUpperInvariant() + ':'
                source = Get-SafeMountSource -Value $mapping.RemotePath
                fstype = 'cifs'
                configured_via = 'hkcu_network'
            }
        })
    }
    [ordered]@{ filesystems = $rows }
}
$script:CensusSections['configured_mounts']['scope'] = 'persisted HKCU drive mappings for collection account only; declarations only'

Invoke-CensusSection -Name interfaces -Commands Get-NetAdapter, Get-NetIPAddress -ArrayData -Query {
    $addresses = @(Get-NetIPAddress)
    Get-NetAdapter -IncludeHidden | ForEach-Object {
        $adapter = $_
        [ordered]@{
            name = [string]$adapter.Name
            interface_index = [int]$adapter.ifIndex
            description = [string]$adapter.InterfaceDescription
            mac_address = [string]$adapter.MacAddress
            status = [string]$adapter.Status
            link_speed = [string]$adapter.LinkSpeed
            addresses = @($addresses | Where-Object { $_.InterfaceIndex -eq $adapter.ifIndex } |
                ForEach-Object {
                    [ordered]@{
                        address = [string]$_.IPAddress
                        prefix_length = [int]$_.PrefixLength
                        family = [string]$_.AddressFamily
                        prefix_origin = [string]$_.PrefixOrigin
                        address_state = [string]$_.AddressState
                    }
                })
        }
    }
}

Invoke-CensusSection -Name dns -Commands Get-DnsClient, Get-DnsClientServerAddress -Query {
    [ordered]@{
        clients = @(Get-DnsClient | ForEach-Object {
            [ordered]@{
                interface_index = [int]$_.InterfaceIndex
                interface_alias = [string]$_.InterfaceAlias
                connection_specific_suffix = [string]$_.ConnectionSpecificSuffix
                register_address = [bool]$_.RegisterThisConnectionsAddress
            }
        })
        servers = @(Get-DnsClientServerAddress | ForEach-Object {
            [ordered]@{
                interface_index = [int]$_.InterfaceIndex
                family = [string]$_.AddressFamily
                server_addresses = @($_.ServerAddresses | ForEach-Object { [string]$_ })
            }
        })
    }
}

Invoke-CensusSection -Name routes -Commands Get-NetRoute -ArrayData -Query {
    Get-NetRoute | ForEach-Object {
        [ordered]@{
            destination_prefix = [string]$_.DestinationPrefix
            next_hop = [string]$_.NextHop
            interface_index = [int]$_.InterfaceIndex
            interface_alias = [string]$_.InterfaceAlias
            metric = [int]$_.RouteMetric
            protocol = [string]$_.Protocol
            state = [string]$_.State
        }
    }
}

Invoke-CensusSection -Name tcp -Commands Get-NetTCPConnection, Get-Process -ArrayData -Query {
    # Listen and all connection states are evidence; direction is not inferred here.
    Get-NetTCPConnection | ForEach-Object {
        [ordered]@{
            local_address = [string]$_.LocalAddress
            local_port = [int]$_.LocalPort
            remote_address = [string]$_.RemoteAddress
            remote_port = [int]$_.RemotePort
            state = [string]$_.State
            process = Get-SafeProcessName -ProcessId $_.OwningProcess
            pid = [uint32]$_.OwningProcess
        }
    }
}

Invoke-CensusSection -Name udp -Commands Get-NetUDPEndpoint, Get-Process -ArrayData -Query {
    # UDP endpoint enumeration has no peer address: do not invent a UDP dependency.
    Get-NetUDPEndpoint | ForEach-Object {
        [ordered]@{
            local_address = [string]$_.LocalAddress
            local_port = [int]$_.LocalPort
            process = Get-SafeProcessName -ProcessId $_.OwningProcess
            pid = [uint32]$_.OwningProcess
        }
    }
}

Invoke-CensusSection -Name services -Commands Get-CimInstance, Get-Service -ArrayData -Query {
    $dependencies = @{}
    Get-Service | ForEach-Object {
        $dependencies[$_.Name] = @($_.RequiredServices | ForEach-Object { [string]$_.Name })
    }
    Get-CimInstance -ClassName Win32_Service | ForEach-Object {
        [ordered]@{
            name = [string]$_.Name
            display_name = [string]$_.DisplayName
            state = [string]$_.State
            start_mode = [string]$_.StartMode
            service_account = [string]$_.StartName
            pid = [uint32]$_.ProcessId
            required_services = @($dependencies[$_.Name])
        }
    }
}

Invoke-CensusSection -Name features -Commands Get-WindowsFeature -ArrayData -Query {
    Get-WindowsFeature | Where-Object { $_.Installed } | ForEach-Object {
        [ordered]@{
            name = [string]$_.Name
            display_name = [string]$_.DisplayName
            install_state = [string]$_.InstallState
            feature_type = [string]$_.FeatureType
        }
    }
}

Invoke-CensusSection -Name installed_software -Commands Get-ItemProperty -ArrayData -Query {
    # Query uninstall metadata instead of Win32_Product (which can trigger MSI repair).
    $paths = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    foreach ($registryPath in $paths) {
        if (Test-Path -Path $registryPath) {
            Get-ItemProperty -Path $registryPath | Where-Object { $_.DisplayName } |
                ForEach-Object {
                    [ordered]@{
                        name = [string]$_.DisplayName
                        version = [string]$_.DisplayVersion
                        publisher = [string]$_.Publisher
                        install_date = [string]$_.InstallDate
                    }
                }
        }
    }
}

Invoke-CensusSection -Name disks -Commands Get-CimInstance -ArrayData -Query {
    Get-CimInstance -ClassName Win32_LogicalDisk | ForEach-Object {
        [ordered]@{
            device_id = [string]$_.DeviceID
            drive_type = [int]$_.DriveType
            filesystem = [string]$_.FileSystem
            volume_name = [string]$_.VolumeName
            size_bytes = $(if ($null -eq $_.Size) { $null } else { [uint64]$_.Size })
            free_bytes = $(if ($null -eq $_.FreeSpace) { $null } else { [uint64]$_.FreeSpace })
            provider_name = Get-SafeMountSource -Value $_.ProviderName
        }
    }
}

Invoke-CensusSection -Name scheduled_tasks -Commands Get-ScheduledTask -ArrayData -Query {
    Get-ScheduledTask | ForEach-Object {
        [ordered]@{
            name = [string]$_.TaskName
            task_path = [string]$_.TaskPath
            state = [string]$_.State
            actions = @($_.Actions | ForEach-Object {
                [ordered]@{
                    action_type = [string]$_.CimClass.CimClassName
                    executable_name = $(if ($_.Execute) { Split-Path -Leaf $_.Execute } else { $null })
                }
            })
            triggers = @($_.Triggers | ForEach-Object {
                [ordered]@{
                    trigger_type = [string]$_.CimClass.CimClassName
                    enabled = [bool]$_.Enabled
                    start_boundary = [string]$_.StartBoundary
                }
            })
        }
    }
}

Invoke-CensusSection -Name firewall -Commands Get-NetFirewallProfile, Get-NetFirewallRule,
    Get-NetFirewallPortFilter, Get-NetFirewallAddressFilter -Query {
    [ordered]@{
        profiles = @(Get-NetFirewallProfile -PolicyStore ActiveStore | ForEach-Object {
            [ordered]@{
                name = [string]$_.Name
                enabled = [string]$_.Enabled
                default_inbound_action = [string]$_.DefaultInboundAction
                default_outbound_action = [string]$_.DefaultOutboundAction
            }
        })
        rules = @(Get-NetFirewallRule -PolicyStore ActiveStore | ForEach-Object {
            $rule = $_
            $portFilter = @($rule | Get-NetFirewallPortFilter)
            $addressFilter = @($rule | Get-NetFirewallAddressFilter)
            [ordered]@{
                name = [string]$rule.Name
                display_name = [string]$rule.DisplayName
                enabled = [string]$rule.Enabled
                direction = [string]$rule.Direction
                action = [string]$rule.Action
                profile = [string]$rule.Profile
                policy_source_type = [string]$rule.PolicyStoreSourceType
                ports = @($portFilter | ForEach-Object {
                    [ordered]@{
                        protocol = [string]$_.Protocol
                        local_ports = @($_.LocalPort | ForEach-Object { [string]$_ })
                        remote_ports = @($_.RemotePort | ForEach-Object { [string]$_ })
                    }
                })
                addresses = @($addressFilter | ForEach-Object {
                    [ordered]@{
                        local_addresses = @($_.LocalAddress | ForEach-Object { [string]$_ })
                        remote_addresses = @($_.RemoteAddress | ForEach-Object { [string]$_ })
                    }
                })
            }
        })
    }
}

Invoke-CensusSection -Name iis -Commands Get-Website, Get-WebBinding -Enabled $IncludeRoleMetadata -ArrayData -Query {
    Get-Website | ForEach-Object {
        $site = $_
        [ordered]@{
            name = [string]$site.Name
            state = [string]$site.State
            application_pool = [string]$site.ApplicationPool
            bindings = @(Get-WebBinding -Name $site.Name | ForEach-Object {
                [ordered]@{
                    protocol = [string]$_.Protocol
                    binding_information = [string]$_.BindingInformation
                    ssl_flags = [int]$_.sslFlags
                }
            })
        }
    }
}

Invoke-CensusSection -Name active_directory -Commands Get-ADDomain, Get-ADDomainController,
    Get-ADForest -Enabled $IncludeRoleMetadata -Query {
    $domain = Get-ADDomain
    $forest = Get-ADForest
    [ordered]@{
        dns_root = [string]$domain.DNSRoot
        domain_mode = [string]$domain.DomainMode
        forest_name = [string]$forest.Name
        forest_mode = [string]$forest.ForestMode
        domains = @($forest.Domains | ForEach-Object { [string]$_ })
        controllers = @(Get-ADDomainController -Filter * | ForEach-Object {
            [ordered]@{
                hostname = [string]$_.HostName
                ipv4_address = [string]$_.IPv4Address
                site = [string]$_.Site
                is_global_catalog = [bool]$_.IsGlobalCatalog
                is_read_only = [bool]$_.IsReadOnly
            }
        })
    }
}

$script:CensusSections['capabilities'] = [ordered]@{
    status = 'ok'
    data = [ordered]@{
        powershell_version = $PSVersionTable.PSVersion.ToString()
        language_mode = [string]$ExecutionContext.SessionState.LanguageMode
        optional_role_metadata_requested = $IncludeRoleMetadata
        smb_mapping_scope = 'current collection session; other user sessions excluded'
        configured_mount_scope = 'persisted HKCU drive mappings for collection account only'
        patch_baseline_status = 'unknown; Get-HotFix is limited inventory, not patch currency'
        memory_scope = 'OS visible physical memory and allocated paging files'
        reboot_indicator_scope = 'CBS, Windows Update and pending file rename registry indicators only'
        commands = @(@(
            'Get-CimInstance', 'Get-NetAdapter', 'Get-NetTCPConnection',
            'Get-NetUDPEndpoint', 'Get-WindowsFeature', 'Get-ScheduledTask',
            'Get-NetFirewallRule', 'Get-Website', 'Get-ADDomain', 'Get-HotFix', 'Get-SmbMapping'
        ) | ForEach-Object {
            [ordered]@{
                name = $_
                available = [bool](Get-Command -Name $_ -ErrorAction SilentlyContinue)
            }
        })
    }
}

$document = [ordered]@{
    schema_version = 1
    asset_id = $InventoryId
    platform = 'windows'
    collected_at = [DateTime]::UtcNow.ToString('o')
    collector = [ordered]@{ name = 'windows_census'; version = '0.4.0' }
    sections = $script:CensusSections
}
Write-Output -NoEnumerate $document
