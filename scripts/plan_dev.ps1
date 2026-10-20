# terraform plan against the real dev AWS account. Never applies.
# Prereq: aws sso login --profile hdp-dev
param([string]$AwsProfile = "hdp-dev")

# the plan must reach the real dev account, never MiniStack
Remove-Item Env:AWS_ENDPOINT_URL -ErrorAction SilentlyContinue
$env:AWS_PROFILE = $AwsProfile
$tf = "infrastructure/terraform"

terraform "-chdir=$tf" init -input=false
if ($LASTEXITCODE) { exit $LASTEXITCODE }
terraform "-chdir=$tf" validate
if ($LASTEXITCODE) { exit $LASTEXITCODE }
# quoted: PowerShell 5.1 splits unquoted "-out=dev.tfplan" at the dot
terraform "-chdir=$tf" plan "-input=false" "-var-file=environments/dev.tfvars" "-out=dev.tfplan"
exit $LASTEXITCODE
