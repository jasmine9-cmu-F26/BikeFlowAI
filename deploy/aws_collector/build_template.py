"""Build a self-contained CloudFormation template; does not contact AWS."""
import argparse
import hashlib
import json
from pathlib import Path


def template(collector_source,adapter_source,collector_sha256):
    inline=collector_source+'\n\n'+adapter_source.replace('import collect_divvy_gbfs as collector','collector = sys.modules[__name__]')
    compile(inline,'index.py','exec')
    ref=lambda name:{'Ref':name}
    sub=lambda value:{'Fn::Sub':value}
    arn=lambda name:{'Fn::GetAtt':[name,'Arn']}
    trust=lambda service:dict(Version='2012-10-17',Statement=[dict(Effect='Allow',Principal={'Service':service},Action='sts:AssumeRole')])
    doc=lambda statements:dict(Version='2012-10-17',Statement=statements)
    allow=lambda action,resource:dict(Effect='Allow',Action=action,Resource=resource)
    scheduler_trust=trust('scheduler.amazonaws.com')
    scheduler_trust['Statement'][0]['Condition']={'StringEquals':{'aws:SourceAccount':ref('AWS::AccountId')},'ArnEquals':{'aws:SourceArn':arn('ScheduleGroup')}}
    resources={
        'DataBucket':dict(Type='AWS::S3::Bucket',DeletionPolicy='Retain',UpdateReplacePolicy='Retain',Properties=dict(
            PublicAccessBlockConfiguration=dict(BlockPublicAcls=True,IgnorePublicAcls=True,BlockPublicPolicy=True,RestrictPublicBuckets=True),
            OwnershipControls=dict(Rules=[dict(ObjectOwnership='BucketOwnerEnforced')]),
            BucketEncryption=dict(ServerSideEncryptionConfiguration=[dict(ServerSideEncryptionByDefault=dict(SSEAlgorithm='AES256'))]))),
        'BucketPolicy':dict(Type='AWS::S3::BucketPolicy',Properties=dict(Bucket=ref('DataBucket'),PolicyDocument=doc([
            dict(Effect='Deny',Principal='*',Action='s3:*',Resource=[arn('DataBucket'),sub('${DataBucket.Arn}/*')],Condition={'Bool':{'aws:SecureTransport':'false'}})]))),
        'LogGroup':dict(Type='AWS::Logs::LogGroup',Properties=dict(LogGroupName=sub('/aws/lambda/${ProjectName}'),RetentionInDays=14)),
        'CollectorRole':dict(Type='AWS::IAM::Role',Properties=dict(AssumeRolePolicyDocument=trust('lambda.amazonaws.com'),Policies=[dict(PolicyName='collector-only',PolicyDocument=doc([
            allow(['s3:GetObject','s3:PutObject'],sub('${DataBucket.Arn}/current_validation/*')),
            allow(['logs:CreateLogStream','logs:PutLogEvents'],sub('arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/lambda/${ProjectName}:*'))]))])),
        'CollectorFunction':dict(Type='AWS::Lambda::Function',DependsOn='LogGroup',Properties=dict(
            FunctionName=ref('ProjectName'),Runtime='python3.14',Handler='index.lambda_handler',Role=arn('CollectorRole'),
            Timeout=90,MemorySize=512,Code=dict(ZipFile=inline),
            Environment=dict(Variables=dict(DATA_BUCKET=ref('DataBucket'),STOP_AT_UTC=ref('StopAtUtc'),COLLECTOR_BASE_SHA256=collector_sha256)))),
        'AsyncPolicy':dict(Type='AWS::Lambda::EventInvokeConfig',Properties=dict(FunctionName=ref('CollectorFunction'),Qualifier='$LATEST',MaximumEventAgeInSeconds=60,MaximumRetryAttempts=0)),
        'ScheduleGroup':dict(Type='AWS::Scheduler::ScheduleGroup',Properties=dict(Name=sub('${ProjectName}-schedule'))),
        'SchedulerRole':dict(Type='AWS::IAM::Role',Properties=dict(AssumeRolePolicyDocument=scheduler_trust,Policies=[dict(PolicyName='invoke-collector-only',PolicyDocument=doc([allow('lambda:InvokeFunction',arn('CollectorFunction'))]))])),
        'CollectionSchedule':dict(Type='AWS::Scheduler::Schedule',DependsOn='AsyncPolicy',Properties=dict(
            Name=sub('${ProjectName}-2min'),GroupName=ref('ScheduleGroup'),State=ref('ScheduleState'),
            ScheduleExpression='rate(2 minutes)',ScheduleExpressionTimezone='UTC',EndDate=ref('StopAtUtc'),FlexibleTimeWindow=dict(Mode='OFF'),
            Target=dict(Arn=arn('CollectorFunction'),RoleArn=arn('SchedulerRole'),Input=json.dumps(dict(scheduled_time='<aws.scheduler.scheduled-time>')),
                RetryPolicy=dict(MaximumEventAgeInSeconds=60,MaximumRetryAttempts=0))))}
    result=dict(AWSTemplateFormatVersion='2010-09-09',Description='BikeFlow AI private Divvy full snapshots: 2-minute Lambda + S3; schedule initially disabled; retained data bucket.',
        Parameters=dict(ProjectName=dict(Type='String',Default='bikeflow-divvy-collector',AllowedPattern='[a-z][a-z0-9-]{2,39}'),
            StopAtUtc=dict(Type='String',Default='2026-12-13T07:59:00Z',AllowedPattern='[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z'),
            ScheduleState=dict(Type='String',Default='DISABLED',AllowedValues=['DISABLED','ENABLED'])),Resources=resources,
        Outputs=dict(DataBucketName=dict(Value=ref('DataBucket')),FunctionName=dict(Value=ref('CollectorFunction')),
            ScheduleName=dict(Value=ref('CollectionSchedule')),ScheduleGroupName=dict(Value=ref('ScheduleGroup')),
            ScheduleState=dict(Value=ref('ScheduleState')),StopAtUtc=dict(Value=ref('StopAtUtc'))))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[2])
    args=p.parse_args();project=args.project_root
    source=(project/'scripts/data/collect_divvy_gbfs.py').read_bytes()
    adapter=(project/'deploy/aws_collector/handler.py').read_text(encoding='utf-8')
    result=template(source.decode('utf-8'),adapter,hashlib.sha256(source).hexdigest())
    output=project/'deploy/aws_collector/template.json'
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
    if output.stat().st_size>51200:raise ValueError('Template exceeds direct CloudFormation upload limit')
    manifest=dict(collector_source_sha256=hashlib.sha256(source).hexdigest(),adapter_sha256=hashlib.sha256((project/'deploy/aws_collector/handler.py').read_bytes()).hexdigest(),
        inline_code_sha256=hashlib.sha256(result['Resources']['CollectorFunction']['Properties']['Code']['ZipFile'].encode()).hexdigest(),template_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    (output.parent/'source_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(template=str(output),bytes=output.stat().st_size,aws_contacted=False,resources_created=False),indent=2))


if __name__=='__main__':main()
