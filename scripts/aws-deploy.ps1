# Deploy trading-bot to AWS EC2 via CloudFormation + S3 + SSM.
# Usage (from repo root, PowerShell):
#   .\scripts\aws-deploy.ps1
# Optional:
#   .\scripts\aws-deploy.ps1 -InstanceType t3.2xlarge -StackName trading-bot-prod
#   .\scripts\aws-deploy.ps1 -Region ap-south-1

param(
  [string]$Region = "eu-north-1",
  [string]$StackName = "trading-bot",
  [string]$InstanceType = "m7i-flex.large",
  [int]$VolumeSizeGiB = 80,
  [string]$AllowedSSHCidr = "127.0.0.1/32"
)

$ErrorActionPreference = "Stop"
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

if (-not (Test-Path (Join-Path $Root ".env"))) {
  throw "Missing .env in repo root. Copy .env.example, set JWT_SECRET, ENCRYPTION_KEY, and Angel One keys first."
}

$identity = aws sts get-caller-identity --output json | ConvertFrom-Json
$Account = $identity.Account
$Bucket = "trading-bot-deploy-$Account-$Region"
Write-Host "Account=$Account Region=$Region Bucket=$Bucket Stack=$StackName"

# Ensure deploy bucket
$bucketExists = $true
try {
  aws s3api head-bucket --bucket $Bucket --region $Region 2>$null | Out-Null
} catch {
  $bucketExists = $false
}
if (-not $bucketExists) {
  Write-Host "Creating S3 bucket $Bucket"
  if ($Region -eq "us-east-1") {
    aws s3api create-bucket --bucket $Bucket --region $Region | Out-Null
  } else {
    aws s3api create-bucket --bucket $Bucket --region $Region --create-bucket-configuration LocationConstraint=$Region | Out-Null
  }
  aws s3api put-public-access-block --bucket $Bucket --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true | Out-Null
}

# Package source (exclude bulky/local artifacts)
$PackageDir = Join-Path $env:TEMP "trading-bot-aws-package"
$PackageFile = Join-Path $env:TEMP "trading-bot-package.tgz"
if (Test-Path $PackageDir) { Remove-Item -Recurse -Force $PackageDir }
New-Item -ItemType Directory -Path $PackageDir | Out-Null

$excludeDirs = @(".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", "dist", "build", "agent-transcripts", ".cursor")
$robocopyArgs = @($Root, $PackageDir, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/nc", "/ns", "/np")
foreach ($d in $excludeDirs) {
  $robocopyArgs += "/XD"
  $robocopyArgs += $d
}
& robocopy @robocopyArgs | Out-Null
# robocopy exit codes 0-7 are success-ish
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with code $LASTEXITCODE" }

# Keep secrets out of S3 - .env is delivered via SSM only
$envPath = Join-Path $PackageDir ".env"
if (Test-Path $envPath) { Remove-Item -Force $envPath }

if (Test-Path $PackageFile) { Remove-Item -Force $PackageFile }
Push-Location $PackageDir
try {
  tar -czf $PackageFile *
} finally {
  Pop-Location
}

$S3Key = "releases/trading-bot-latest.tgz"
$S3Uri = "s3://$Bucket/$S3Key"
Write-Host "Uploading package to $S3Uri (no .env in package)"
aws s3 cp $PackageFile $S3Uri --region $Region | Out-Null
aws s3 cp (Join-Path $Root "infra\aws\remote-up.sh") "s3://$Bucket/scripts/remote-up.sh" --region $Region | Out-Null

# Store .env as SecureString in SSM (not in S3). Avoid file:// paths with spaces.
$EnvParam = "/trading-bot/$StackName/dotenv"
Write-Host "Writing secrets to SSM parameter $EnvParam"
$envRaw = [System.IO.File]::ReadAllText((Join-Path $Root ".env"))
if ($envRaw.Length -lt 40) { throw ".env looks empty or too short ($($envRaw.Length) chars)" }
$putBody = @{
  Name      = $EnvParam
  Type      = "SecureString"
  Value     = $envRaw
  Overwrite = $true
} | ConvertTo-Json -Compress -Depth 5
$putFile = Join-Path $env:TEMP "trading-bot-ssm-put.json"
[System.IO.File]::WriteAllText($putFile, $putBody, (New-Object System.Text.UTF8Encoding $false))
aws ssm put-parameter --region $Region --cli-input-json "file://$putFile" | Out-Null
Remove-Item -Force $putFile -ErrorAction SilentlyContinue
$storedLen = aws ssm get-parameter --region $Region --name $EnvParam --with-decryption --query "length(Parameter.Value)" --output text
if ([int]$storedLen -lt 40) { throw "SSM parameter store failed (stored length=$storedLen)" }
Write-Host "SSM dotenv stored ($storedLen chars)"

# Deploy / update CloudFormation
$Template = Join-Path $Root "infra\aws\cloudformation.yml"
$params = @(
  "ParameterKey=InstanceType,ParameterValue=$InstanceType",
  "ParameterKey=VolumeSizeGiB,ParameterValue=$VolumeSizeGiB",
  "ParameterKey=AllowedSSHCidr,ParameterValue=$AllowedSSHCidr",
  "ParameterKey=DeployBucketName,ParameterValue=$Bucket"
)

$stackStatus = $null
try {
  $stackStatus = aws cloudformation describe-stacks --stack-name $StackName --region $Region --query "Stacks[0].StackStatus" --output text 2>$null
} catch {
  $stackStatus = $null
}

if ($stackStatus -eq "ROLLBACK_COMPLETE" -or $stackStatus -eq "ROLLBACK_FAILED" -or $stackStatus -eq "CREATE_FAILED" -or $stackStatus -eq "DELETE_FAILED") {
  Write-Host "Deleting failed stack $StackName (status=$stackStatus) before recreate..."
  aws cloudformation delete-stack --stack-name $StackName --region $Region
  aws cloudformation wait stack-delete-complete --stack-name $StackName --region $Region
  $stackStatus = $null
}

if (-not $stackStatus -or $stackStatus -eq "None") {
  Write-Host "Creating CloudFormation stack $StackName ..."
  aws cloudformation create-stack `
    --stack-name $StackName `
    --region $Region `
    --template-body "file://$Template" `
    --capabilities CAPABILITY_NAMED_IAM `
    --parameters $params | Out-Null
  aws cloudformation wait stack-create-complete --stack-name $StackName --region $Region
} else {
  Write-Host "Updating CloudFormation stack $StackName (status=$stackStatus) ..."
  $prevEap = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $updateOut = aws cloudformation update-stack `
    --stack-name $StackName `
    --region $Region `
    --template-body "file://$Template" `
    --capabilities CAPABILITY_NAMED_IAM `
    --parameters $params 2>&1 | Out-String
  $updateCode = $LASTEXITCODE
  $ErrorActionPreference = $prevEap
  if ($updateCode -eq 0) {
    aws cloudformation wait stack-update-complete --stack-name $StackName --region $Region
  } elseif ($updateOut -match "No updates are to be") {
    Write-Host "No stack updates required."
  } else {
    Write-Host $updateOut
    throw "CloudFormation update-stack failed (exit=$updateCode)"
  }
}

$outputs = aws cloudformation describe-stacks --stack-name $StackName --region $Region --query "Stacks[0].Outputs" --output json | ConvertFrom-Json
$PublicIp = ($outputs | Where-Object { $_.OutputKey -eq "PublicIp" }).OutputValue
$InstanceId = ($outputs | Where-Object { $_.OutputKey -eq "InstanceId" }).OutputValue
Write-Host "InstanceId=$InstanceId PublicIp=$PublicIp"

Write-Host "Waiting for SSM agent..."
$ready = $false
for ($i = 0; $i -lt 36; $i++) {
  $ping = aws ssm describe-instance-information --region $Region --filters "Key=InstanceIds,Values=$InstanceId" --query "InstanceInformationList[0].PingStatus" --output text 2>$null
  if ($ping -eq "Online") { $ready = $true; break }
  Start-Sleep -Seconds 10
}
if (-not $ready) {
  throw "Instance did not come online in SSM. Check IAM instance profile / VPC endpoints / amazon-ssm-agent."
}

$commands = @(
  "set -euo pipefail",
  "export AWS_DEFAULT_REGION='$Region'",
  "export PACKAGE_S3_URI='$S3Uri'",
  "export PUBLIC_HOST='$PublicIp'",
  "export ENV_PARAM='$EnvParam'",
  "aws s3 cp s3://$Bucket/scripts/remote-up.sh /tmp/remote-up.sh --region $Region",
  "sed -i 's/\r$//' /tmp/remote-up.sh",
  "chmod +x /tmp/remote-up.sh",
  "bash /tmp/remote-up.sh"
)

$paramsJson = @{ commands = $commands } | ConvertTo-Json -Compress
$paramsFile = Join-Path $env:TEMP "ssm-params.json"
# AWS CLI rejects UTF-8 BOM from Set-Content -Encoding utf8
[System.IO.File]::WriteAllText($paramsFile, $paramsJson, (New-Object System.Text.UTF8Encoding $false))

Write-Host "Sending SSM deploy command..."
$cmdId = aws ssm send-command `
  --region $Region `
  --instance-ids $InstanceId `
  --document-name "AWS-RunShellScript" `
  --comment "Deploy trading-bot Compose stack" `
  --parameters "file://$paramsFile" `
  --query "Command.CommandId" `
  --output text

if (-not $cmdId -or $cmdId -eq "None") {
  throw "SSM send-command did not return a CommandId. Check $paramsFile"
}

Write-Host "CommandId=$cmdId - waiting for completion (build can take several minutes)..."
$finalStatus = $null
for ($i = 0; $i -lt 120; $i++) {
  Start-Sleep -Seconds 20
  $prevEap = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $status = aws ssm get-command-invocation --region $Region --command-id $cmdId --instance-id $InstanceId --query Status --output text 2>$null
  $ErrorActionPreference = $prevEap
  $finalStatus = "$status".Trim()
  Write-Host "SSM status=$finalStatus"
  if ($finalStatus -in @("Success", "Cancelled", "TimedOut", "Failed")) { break }
}

$outFile = Join-Path $env:TEMP "ssm-deploy-out.txt"
$errFile = Join-Path $env:TEMP "ssm-deploy-err.txt"
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
aws ssm get-command-invocation --region $Region --command-id $cmdId --instance-id $InstanceId --query StandardOutputContent --output text 2>$null | Out-File $outFile -Encoding utf8
aws ssm get-command-invocation --region $Region --command-id $cmdId --instance-id $InstanceId --query StandardErrorContent --output text 2>$null | Out-File $errFile -Encoding utf8
$ErrorActionPreference = $prevEap

Write-Host "---- stdout (tail) ----"
if (Test-Path $outFile) { Get-Content $outFile -Tail 80 }
Write-Host "---- stderr (tail) ----"
if (Test-Path $errFile) { Get-Content $errFile -Tail 40 }

if ($finalStatus -ne "Success") {
  throw "Remote deploy failed with status $finalStatus"
}

Write-Host ""
Write-Host "Deploy complete."
Write-Host ("App URL:  http://{0}/" -f $PublicIp)
Write-Host ("Angel One SmartAPI: register public IP {0}" -f $PublicIp)
Write-Host ("SSM shell: aws ssm start-session --target {0} --region {1}" -f $InstanceId, $Region)
