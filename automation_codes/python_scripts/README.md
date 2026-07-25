## Scripts for generating lambda api terraform

#### For creating data.tf
[resource_generation.py](./resource_generation.py)

#### Code that gets generated:
* /../terraforms/api_integration.tf
* /../terraforms/data.tf
* /../terraforms/lambda.tf
* /../terraforms/s3_data.tf

### How to customize lambdas:

Each lambda function can be customized to allow different methods when integrated with the API Gateway.  Users must update these parameters based on the lambda function requirements.

Possible ```integrations.json``` parameters:
```json
{
  "methods": ["GET", "POST", "OPTIONS"] ,
  "lambda_name": "ccd_annual_calcs",
  "full_path": "/jw-api/app-config",
  "layers": [],
  "additional_policies": ["lambda_role_policy_boto3_support"],
  "timeout": "300",
  "memory_size": "128",
  "additional_security_groups": ["lambda_external_tcp_egress_security_group"],
  "environmental_variables": {
    "LOGGER_LEVEL": "INFO"
  }
}
```
Required ```integrations.json``` parameters:
```json
{
  "methods": ["GET", "POST", "OPTIONS"] ,
  "lambda_name": "ccd_annual_calcs",
  "full_path": "/ccd-calcs/calcs",
  "layers": ["common_ccd_dal"]
}
```

#### How to test:

From the [automation_codes/python_scripts directory](.)

Provide the environment type and rest api name.

```bash
python3 generate_tf.py --env dev --rest_api jw-api 
```

## TODO
- Use memory parameter of ```integration.json```