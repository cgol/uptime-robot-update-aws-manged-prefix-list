#!/bin/bash

# UptimeRobot IP Manager Deployment Script
# This script packages and deploys a Lambda function via CloudFormation

set -e

# Configuration
STACK_NAME="uptimerobot-ip-manager"
FUNCTION_NAME="uptimerobot-ip-manager"
S3_BUCKET=""
AWS_REGION=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
print_usage() {
    echo "Usage: $0 -b <s3-bucket> [-r <aws-region>] [-s <stack-name>] [-f <function-name>]"
    echo ""
    echo "Optional:"
    echo "  -b    S3 bucket name for storing Lambda deployment package if left blank will look for a bucket commencing with cf-templates"
    echo "  -r    AWS region (default: current AWS CLI default region)"
    echo "  -s    CloudFormation stack name (default: uptimerobot-ip-manager)"
    echo "  -f    Lambda function name (default: uptimerobot-ip-manager)"
    echo ""
    echo "Example:"
    echo "  $0 -b my-lambda-deployments -r us-east-1"
}

log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Parse command line arguments
while getopts "b:r:s:f:h" opt; do
    case $opt in
        b) S3_BUCKET="$OPTARG" ;;
        r) AWS_REGION="$OPTARG" ;;
        s) STACK_NAME="$OPTARG" ;;
        f) FUNCTION_NAME="$OPTARG" ;;
        h) print_usage; exit 0 ;;
        \?) error "Invalid option -$OPTARG"; print_usage; exit 1 ;;
    esac
done

# Set AWS region if not provided
if [[ -z "$AWS_REGION" ]]; then
    AWS_REGION=$(aws configure get region)
    if [[ -z "$AWS_REGION" ]]; then
        AWS_REGION="us-east-1"
        warn "No AWS region specified, using default: $AWS_REGION"
    else
        log "Using AWS region from CLI configuration: $AWS_REGION"
    fi
fi

# Validate required parameters - if no bucket supplied look for a default bucket commencing with cf-templates
if [[ -z "$S3_BUCKET" ]]; then
    S3_BUCKET=$(aws s3 ls | grep cf-templates | grep $AWS_REGION | awk '{print $3}')
fi

if [[ -z "$S3_BUCKET" ]]; then
    error "S3 bucket is required (-b parameter)"
    print_usage
    exit 1
fi

log "Starting deployment process..."
log "Stack Name: $STACK_NAME"
log "Function Name: $FUNCTION_NAME" 
log "S3 Bucket: $S3_BUCKET"
log "AWS Region: $AWS_REGION"

# Check if required files exist
if [[ ! -f "lambda_function.py" ]]; then
    error "lambda_function.py not found in current directory"
    exit 1
fi

if [[ ! -f "uptimerobot-ip-manager.yaml" ]]; then
    error "uptimerobot-ip-manager.yaml not found in current directory"
    exit 1
fi

# Check that the account has the necessary quota for prefix lists
log "Checking AWS service quotas for prefix lists..."
QUOTA=$(aws service-quotas get-service-quota --service-code vpc --quota-code L-0EA8095F --region "$AWS_REGION" --query 'Quota.Value' --output text)
if [[ $? -ne 0 ]]; then
    error "Failed to retrieve service quota for prefix lists"
    exit 1
fi

# Remove the decimal point and any characters after it
QUOTA=${QUOTA%.*}

if (( $(echo "$QUOTA < 120" | bc -l) )); then
    warn "Current prefix list quota is $QUOTA, which is below the minimum needed by uptimerobot of 120"
    warn "uptime robot returns 116 entries at time of writing - a quota of 142 is recommended as it allows for future growth and allows up to 7 security groups per network interface."
    error "Please request a quota increase via AWS Support and wait approval before running again."
    exit 1
else
    log "Current prefix list quota is sufficient: $QUOTA"
fi

# Create temporary directory for packaging
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

log "Creating Lambda deployment package..."

# Copy Lambda function to temp directory
cp lambda_function.py "$TEMP_DIR/"

# Create ZIP file
cd "$TEMP_DIR"
zip -r lambda-function.zip lambda_function.py
cd - > /dev/null

# Check if S3 bucket exists
log "Checking S3 bucket: $S3_BUCKET"
if ! aws s3 ls "s3://$S3_BUCKET" --region "$AWS_REGION" > /dev/null 2>&1; then
    error "S3 bucket '$S3_BUCKET' does not exist or is not accessible"
    exit 1
fi

# Upload Lambda package to S3 with a random key to force a new lambda deployment
log "Uploading Lambda package to S3 bucket: $S3_BUCKET"
RANDOM_KEY=$(date +%s)-lambda-function.zip
S3_KEY="lambda-deployments/uptimerobot-ip-manager/$RANDOM_KEY"
log "Uploading Lambda package to s3://$S3_BUCKET/$S3_KEY"

aws s3 cp "$TEMP_DIR/lambda-function.zip" "s3://$S3_BUCKET/$S3_KEY" --region "$AWS_REGION"

# Check if CloudFormation stack exists
log "Checking if CloudFormation stack exists..."
if aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" > /dev/null 2>&1; then
    log "Stack exists, performing update..."
    OPERATION="update-stack"
    OPERATION_DESC="update"
else
    log "Stack does not exist, creating new stack..."
    OPERATION="create-stack"
    OPERATION_DESC="create"
fi

# Deploy CloudFormation stack
log "Starting stack $OPERATION_DESC..."

aws cloudformation $OPERATION \
    --stack-name "$STACK_NAME" \
    --template-body file://uptimerobot-ip-manager.yaml \
    --parameters \
        ParameterKey=FunctionName,ParameterValue="$FUNCTION_NAME" \
        ParameterKey=S3Bucket,ParameterValue="$S3_BUCKET" \
        ParameterKey=S3Key,ParameterValue="$S3_KEY" \
        ParameterKey=MaxEntriesPerSecurityGroup,ParameterValue="$QUOTA" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$AWS_REGION"

# Wait for stack operation to complete
log "Waiting for stack $OPERATION_DESC to complete..."

aws cloudformation wait stack-${OPERATION_DESC}-complete \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION"

# Check the final status
STACK_STATUS=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --query 'Stacks[0].StackStatus' \
    --output text)

if [[ "$STACK_STATUS" == *"COMPLETE" ]]; then
    log "Stack $OPERATION_DESC completed successfully!"
    
    # Get stack outputs
    log "Stack outputs:"
    aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION" \
        --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
        --output table
    
    log "Deployment completed successfully!"
    log ""
    log "Next steps:"
    log "1. The Lambda function will run daily to update the AWS managed prefix lists with UptimeRobot IPs."
    log "2. Check CloudWatch Logs for execution details: /aws/lambda/$FUNCTION_NAME"
    log "3. Monitor the created prefix lists: uptimerobot4 and uptimerobot6"
    log "4. You can now reference these prefix lists in your security groups"
    
    # Test the function
    read -p "Would you like to test the Lambda function now? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log "Invoking Lambda function for testing..."
        aws lambda invoke \
            --function-name "$FUNCTION_NAME" \
            --region "$AWS_REGION" \
            --payload '{}' \
            response.json
        
        log "Lambda response:"
        cat response.json | jq .
        rm -f response.json
    fi
    
else
    error "Stack $OPERATION_DESC failed with status: $STACK_STATUS"
    
    # Show stack events for troubleshooting
    log "Recent stack events:"
    aws cloudformation describe-stack-events \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION" \
        --query 'StackEvents[0:10].[Timestamp,LogicalResourceId,ResourceStatus,ResourceStatusReason]' \
        --output table
    
    exit 1
fi