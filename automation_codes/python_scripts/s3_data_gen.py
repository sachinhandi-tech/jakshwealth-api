from resource_generation import resource_gen


def s3_data_tf(s3bucket, name, resource_type, s3_key):
    return f"data \"aws_s3_bucket_object\" \"{name}_{resource_type}\" {'{'}\n\t" \
           f"bucket = \"{s3bucket}\"\n\t" \
           f"key = \"{s3_key}\"\n" \
           "}\n"


def s3_data_gen(env, code_dir, terraform_dir, lambda_s3_bucket):
    directories = resource_gen(code_dir)
    internal_lambdas = directories['internal_lambda']

    s3_bucket = 'jakshwealth-artifacts-' + env
    s3_data_list = list()

    for internal_lambda in internal_lambdas:
        s3_data_list.append({
            "s3bucket": s3_bucket,
            "s3_key": lambda_s3_bucket + "/" + internal_lambda + '.zip',
            "name": internal_lambda,
            "resource_type": "lambda"
        })

    s3_data_source_string = ''
    for s3_data in s3_data_list:
        s3_data_source_string += s3_data_tf(**s3_data)

    with open(terraform_dir + '/s3_data.tf', 'w') as file:
        file.write(s3_data_source_string)
