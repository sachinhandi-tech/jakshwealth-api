import os
import json
from get_module_source import get_module_source

DEFAULT_SG = "\"${aws_security_group.lambda_security_group.id}\""


# TODO allow memory as an input
# Requires a change to infrastructure code as well. . .need variable, etc.
def lambda_generation(function_name, code_dir, subnet_group, timeout='900', alarm_duration='890000',
                      memory_size='128', ephemeral_memory='512', security_groups_str=None,
                      environmental_variables=None, enable_vpc=False):
    """
    Generates and returns a string representing the module for a
    specific {funciton_name} lambda's terraform.
    :param function_name: (str) The name of the lambda function.
    :param code_dir: (str) Parent directory containing lambda sub directories.
    :param timeout: (str) Default timeout used to generated Lambdas TODO not currently an option to change
    :param security_groups_str: (str) Comma separated groups of security group id strings.
           Ex. "\"${aws_security_group.lambda_security_group.id}\", \"${aws_security_group.lambda_security_group2.id}\""
    :return: (str) The module for the given {function_name}
    """

    if not security_groups_str:
        security_groups_str = DEFAULT_SG

    env_variables = f"{environmental_variables}".replace("\'", "\"")
    runtime = ""

    runtime_lambda_functions = ["jw_authentication", "jw_authorization", "jw_secure_data", "jw_app_config"]


    if function_name in runtime_lambda_functions:
        runtime = "runtime = \"python3.12\"\n"

    if enable_vpc:
        vpc_config = (
            f"subnet_ids = \"${'{'}data.aws_subnets.{subnet_group}-subnets.ids{'}'}\"\n\t"
            f"security_group_ids = [{security_groups_str}]\n\t"
        )
    else:
        vpc_config = (
            "subnet_ids = []\n\t"
            "security_group_ids = []\n\t"
            "alert_funnel_arn = \"\"\n\t"
            "enable_log_subscription = false\n\t"
        )

    return f"module \"{function_name}\" {'{'}\n\t" \
           f"source = \"{get_module_source('lambda')}\"\n\t" \
           f"function_name = \"{function_name}\"\n\t" \
           f"description = \"JakshWealth Lambda {function_name}\"\n\t" \
           f"s3artifactbucket = \"${'{'}data.aws_s3_bucket_object.{function_name}_lambda.bucket{'}'}\"\n\t" \
           f"s3artifactkey = \"${'{'}data.aws_s3_bucket_object.{function_name}_lambda.key{'}'}\"\n\t" \
           f"s3objectversion = \"${'{'}data.aws_s3_bucket_object.{function_name}_lambda.version_id{'}'}\"\n\t" \
           f"timeout = \"{timeout}\"\n\t" \
           f"{runtime}" \
           f"memory_size = \"{memory_size}\"\n\t" \
           f"ephemeral_memory = \"{ephemeral_memory}\"\n\t" \
           f"alarm_duration = \"{alarm_duration}\"\n\t" \
           "layers = []\n\t" \
           "tags = \"${var.cigna_tags}\"\n\t" \
           "environment = \"${var.shortenvironment}\"\n\t" \
           f"environmental_variables = {env_variables}\n\t" \
           f"{vpc_config}" \
           "}\n"


def get_security_groups_str(integration_parameters=None):
    """
    Gets the list of terraform security group id strings for use in lambda.
    :param integration_parameters: (dict) Parameters provided by integration.json in dictionary form.
    :return: (str) String with concatenated security group id strings.
    Ex. "\"${aws_security_group.lambda_security_group.id}\", \"${aws_security_group.lambda_security_group2.id}\""
    """

    # Start with the default security group for apis attached.
    # security_group_list = ["${aws_security_group.lambda_security_group.id}"]
    security_groups_str = DEFAULT_SG

    if 'additional_security_groups' in integration_parameters:
        security_groups = integration_parameters['additional_security_groups']

        if security_groups:
            for security_group in security_groups:
                security_groups_str += f", \"${'{'}aws_security_group.{security_group}.id{'}'}\""

    return security_groups_str


def get_lambda_functions_list(code_dir):
    """
    Walks the lambda code directory for unique sub directories.
    :param code_dir: (str) Parent directory containing lambda sub directory.
    :return: (list) A list (str) of directories within {code_dir}/lambda
    """
    dirs = os.walk(code_dir + '/lambda').__next__()[1]
    lambda_functions = list()
    for directory in dirs:
        with open(code_dir + '/lambda/' + directory + '/integration.json') as json_file:
            json.load(json_file)
        lambda_functions.append(directory)

    return lambda_functions


def create_lambda_tf(env, code_dir, terraform_dir):
    """
    Generate the lambda function terraform within {terraform_dir}/lambda.tf
    :param env: (str) environment being executed. Ex. dev
    :param code_dir: (str) Parent directory containing lambda and layers sub directories.
    :param terraform_dir: (str) Directory to place the terraform file.
    :return: None
    """

    with open('user_params.json') as json_file:
        user_params = json.load(json_file)
        enable_vpc = user_params.get('enable_lambda_vpc', False)

    # Get the list of lambda functions in {the code_dir}
    lambda_functions = get_lambda_functions_list(code_dir)

    lambda_dirs_strings = str()
    for lambda_function in lambda_functions:
        directory = 'lambda/' + lambda_function
        with open(code_dir + '/' + directory + '/integration.json') as json_file:
            lambda_integration_parameters = json.load(json_file)

        if 'timeout' not in lambda_integration_parameters:
            lambda_integration_parameters['timeout'] = '30' if lambda_function == 'jw_authorization' else '900'

        if 'alarm_duration' not in lambda_integration_parameters:
            # setting default value of 890000 ms
            lambda_integration_parameters['alarm_duration'] = '890000'

        if 'memory_size' not in lambda_integration_parameters:
            lambda_integration_parameters['memory_size'] = '128'

        if 'ephemeral_memory' not in lambda_integration_parameters:
            lambda_integration_parameters['ephemeral_memory'] = '512'
        elif ('ephemeral_memory' in lambda_integration_parameters) and (
                int(lambda_integration_parameters['ephemeral_memory']) > 10240):
            # Size is too large so we'll default to max.
            lambda_integration_parameters['ephemeral_storage'] = '10240'

        if 'environmental_variables' not in lambda_integration_parameters:
            lambda_integration_parameters['environmental_variables'] = {}

        # setting default value to golden
        subnet_group = 'golden'
        if 'internet' in lambda_integration_parameters:
            if lambda_integration_parameters['internet'] == 'false':
                subnet_group = 'pod'

        # Get the module string representing the {lambda_function}'s terraform
        lambda_dirs_strings += lambda_generation(function_name=lambda_function,
                                                 code_dir=code_dir,
                                                 subnet_group=subnet_group,
                                                 timeout=lambda_integration_parameters['timeout'],
                                                 memory_size=lambda_integration_parameters['memory_size'],
                                                 ephemeral_memory=lambda_integration_parameters['ephemeral_memory'],
                                                 alarm_duration=lambda_integration_parameters['alarm_duration'],
                                                 security_groups_str=get_security_groups_str(
                                                     integration_parameters=lambda_integration_parameters),
                                                 environmental_variables=lambda_integration_parameters[
                                                     'environmental_variables'],
                                                 enable_vpc=enable_vpc)

        # Update role if needed
        update_policies_if_needed(env, lambda_integration_parameters, terraform_dir)

    with open(terraform_dir + '/lambda.tf', 'w') as file:
        file.write(lambda_dirs_strings)


def update_policies_if_needed(env, lambda_integration_parameters, terraform_dir):
    """
    Updates the lambda function role policies if additional policies exist.
    Updates the existing {terraform_dir}/lambda_role.tf with the additional policies.

    :param lambda_integration_parameters: (dict) Dictionary of lambda specific parameters.
    Ex. {'methods': ['GET', 'POST', 'OPTIONS'], 'lambda_name': 'ccd_annual_calcs', 'full_path': '/ccd-calcs/calcs',
     'layers': ['common_ccd_dal'], 'additional_policies': ['lambda_role_policy_boto3_support'],
      'timeout': '300', 'memory': '128'}
    :param terraform_dir: (str) Directory to place the terraform file.
    :return: None
    """
    if 'additional_policies' in lambda_integration_parameters:

        # Adds data source for lambda role
        _lambda_name = lambda_integration_parameters.get('lambda_name')

        role_name = _lambda_name + f"_{env}" + "_role"
        lambda_role_data = (f"""data "aws_iam_role" "{role_name}" {'{'}\n\t
                            name = \"jw_{_lambda_name}_{env}\"\n
                            {'}'}\n""")

        for policy in lambda_integration_parameters['additional_policies']:
            additional_attachments = f"resource \"aws_iam_policy\" \"{policy}_policy\" {'{'}\n\t" \
                                     f"name = \"${'{'}upper(var.team_name){'}'}_{policy}\"\n\t" \
                                     f"policy = \"${'{'}file(\"./data/{policy}.json\"){'}'}\"\n" \
                                     "}\n" \
                                     f"resource \"aws_iam_role_policy_attachment\" \"{policy}_attachment\" {'{'}\n\t" \
                                     f"role = data.aws_iam_role.{role_name}.name\n\t" \
                                     f"policy_arn = \"${'{'}aws_iam_policy.{policy}_policy.arn{'}'}\"\n\t" \
                                     f"depends_on = [data.aws_iam_role.{role_name}]\n" \
                                     "}\n"

            with open(terraform_dir + "/lambda_role.tf", 'a') as role_file:
                role_file.writelines(lambda_role_data)
                role_file.writelines(additional_attachments)
