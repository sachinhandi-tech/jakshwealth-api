import argparse
import json

from resource_generation import resource_gen, create_data_tf
from lambda_terraform_gen import create_lambda_tf
from api_gateway_integration_creation import api_integration_gen
from s3_data_gen import s3_data_gen

CODE_DIRECTORY = '../..'
TERRAFORM_DIRECTORY = '../terraforms'


def generate_tf(env, rest_api):
    with open('user_params.json') as json_file:
        data = json.load(json_file)
        lambda_s3_bucket = data['s3_bucket_details']['lambda_bucket']

    create_data_tf(lambda_directories=resource_gen(CODE_DIRECTORY),
                   terraform_dir=TERRAFORM_DIRECTORY,
                   rest_api_name=rest_api)

    create_lambda_tf(env=env,
                     code_dir=CODE_DIRECTORY,
                     terraform_dir=TERRAFORM_DIRECTORY)

    api_integration_gen(env, CODE_DIRECTORY, TERRAFORM_DIRECTORY)

    s3_data_gen(env, CODE_DIRECTORY, TERRAFORM_DIRECTORY, lambda_s3_bucket=lambda_s3_bucket)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env')
    parser.add_argument('--rest_api', default='jw-api')
    env = parser.parse_args().env
    rest_api = parser.parse_args().rest_api

    generate_tf(env=env, rest_api=rest_api)


if __name__ == "__main__":
    main()
