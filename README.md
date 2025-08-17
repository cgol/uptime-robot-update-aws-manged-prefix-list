# uptime-robot-update-aws-manged-prefix-list
Lambda function that automatically updates AWS Managed IP prefix lists to allow-list IPs used by Uptime Robot. The Prefix Lists can be referecned by Security Groups to allow Uptime Robot access to applications.

## Overview

The Lambda function:
- Fetches the latest IP addresses from UptimeRobot's ip.uptimerobot.com DNS entry A and AAAA types
- Consolidates large IP lists into CIDR ranges to stay within AWS limits (120 entries per prefix list - your account will need a quota increase from the default 60)
- Creates/updates two managed prefix lists: `uptimerobot4` (IPv4) and `uptimerobot6` (IPv6)
- Runs daily via EventBridge to keep the lists current
- Provides comprehensive logging for monitoring and troubleshooting

Note - The basic code structure was initially generated with Claude 4.0 and then fixed manually

## Files

- `lambda_function.py` - The main Lambda function code with enhanced logging
- `uptimerobot-ip-manager.yaml` - CloudFormation template for deployment
- `deploy.sh` - Automated deployment script
- `README.md` - This documentation

## Prerequisites

- AWS CLI configured with appropriate permissions
- An S3 bucket for storing the Lambda deployment package - or it will try to find the default cf-templates bucket for the account and region
- IAM permissions for:
  - Lambda function management
  - EC2 managed prefix lists (create, modify, describe)
  - EventBridge rules
  - S3 object upload
  - CloudFormation stack operations

## Quick Deployment

1. **Clone/download all files to a directory**

2. **Make the deployment script executable:**
   ```bash
   chmod +x deploy.sh
   ```

3. **Run the deployment script:**
   ```bash
   ./deploy.sh <-b your-s3-bucket-name> <-r us-east-1>
   ```

   Replace `your-s3-bucket-name` with an existing S3 bucket in your account if you don't have a cf-templates bucket

## Manual Deployment

If you prefer manual deployment:

1. **Package the Lambda function:**
   ```bash
   zip lambda-function.zip lambda_function.py
   ```

2. **Upload to S3:**
   ```bash
   aws s3 cp lambda-function.zip s3://your-bucket/lambda-function.zip
   ```

3. **Deploy CloudFormation stack:**
   ```bash
   aws cloudformation create-stack \
     --stack-name uptimerobot-ip-manager \
     --template-body file://uptimerobot-ip-manager.yaml \
     --parameters \
       ParameterKey=S3Bucket,ParameterValue=your-bucket \
       ParameterKey=S3Key,ParameterValue=lambda-function.zip \
     --capabilities CAPABILITY_NAMED_IAM
   ```

## Configuration

### Parameters

- `FunctionName` (default: uptimerobot-ip-manager) - Name for the Lambda function
- `S3Bucket` (required) - S3 bucket containing the deployment package  
- `S3Key` (default: lambda-function.zip) - S3 object key for the package

### Schedule

The function runs daily at a random time. To change this, modify the `ScheduleExpression` in the CloudFormation template:

```yaml
ScheduleExpression: "rate(1 day)" 
```

## Usage

### In Security Groups

Once deployed, reference the prefix lists in your security groups:

```bash
# Allow UptimeRobot IPv4 monitoring traffic
aws ec2 authorize-security-group-ingress \
  --group-id sg-12345678 \
  --protocol tcp \
  --port 443 \
  --source-prefix-list-id pl-12345678  # uptimerobot4 prefix list ID

# Allow UptimeRobot IPv6 monitoring traffic  
aws ec2 authorize-security-group-ingress \
  --group-id sg-12345678 \
  --protocol tcp \
  --port 443 \
  --source-prefix-list-id pl-87654321  # uptimerobot6 prefix list ID
```

### In CloudFormation Templates

```yaml
SecurityGroupIngress:
  - IpProtocol: tcp
    FromPort: 443
    ToPort: 443
    SourcePrefixListId: !Ref UptimeRobotIPv4PrefixList
  - IpProtocol: tcp
    FromPort: 443 
    ToPort: 443
    SourcePrefixListId: !Ref UptimeRobotIPv6PrefixList
```

## Monitoring

### CloudWatch Logs

Monitor the function execution in CloudWatch Logs:
- Log Group: `/aws/lambda/uptimerobot-ip-manager`
- The function provides detailed logging including:
  - API response parsing
  - IP consolidation process
  - Prefix list operations
  - Error details with stack traces

### CloudWatch Metrics

Standard Lambda metrics are available:
- Duration
- Errors  
- Invocations
- Throttles

### Manual Testing

Test the function manually:

```bash
aws lambda invoke \
  --function-name uptimerobot-ip-manager \
  --payload '{}' \
  response.json && cat response.json
```

## Troubleshooting

### Common Issues

1. **Prefix List Limits**
   - AWS allows max 60 entries per prefix list by default, but can be increased with a quota increase request (aws support ticket)
   - Function automatically consolidates IPs into CIDR ranges
   - Consolidation process is logged with details

2. **Permission Issues**
   - Ensure the Lambda execution role has EC2 prefix list permissions
   - Check CloudFormation stack events for IAM-related failures

### Debug Logging

To enable debug logging, update the Lambda environment variable:

```bash
aws lambda update-function-configuration \
  --function-name uptimerobot-ip-manager \
  --environment Variables='{LOG_LEVEL=DEBUG}'
```

## Cost Considerations

- Lambda execution: ~$0.01/month (assuming 1-second executions daily)
- Managed prefix lists: Free (within AWS limits)
- EventBridge rules: Free (within AWS limits)
- S3 storage: Minimal cost for deployment package

## Security

The solution follows AWS security best practices:
- Least-privilege IAM role
- No hardcoded credentials
- Encrypted CloudWatch logs
- Tagged resources for governance
- No sensitive data in environment variables

## IP Consolidation Algorithm

Uses the standard python ipaddress.collapse_address() function to change a discrete set of consecutive IP addresses to CIDRs for the prefix list 

## Updates

To update the function:

1. Modify `lambda_function.py`
2. Run the deployment script again:
   ```bash
   ./deploy.sh -b your-s3-bucket -r your-region
   ```

The script automatically detects existing stacks and performs updates.

## Support

For issues:
1. Check CloudWatch Logs for detailed error information
2. Verify UptimeRobot API accessibility
3. Ensure proper IAM permissions
4. Review CloudFormation stack events

## License

This solution uses the MIT license