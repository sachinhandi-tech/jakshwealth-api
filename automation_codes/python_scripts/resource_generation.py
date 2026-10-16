import json
import os

def resource_gen(code_dir):
    """
    Returns a dictionary of directories contained within the given {code_dir}

    :param code_dir: (str) Path to parent directory containing Lambda and Layer code directories.
    :return: Returns a dictionary of directories contained within the given {code_dir}

    Ex.
    Ex. {'internal_lambda': ['ccd_annual_calcs'], 'external_lambda': [],
    'internal_layers': ['common_ccd_dal', 'layer_pandas'], 'external_layers': [],
    'internal_parent_integration': ['/ccd-calcs'], 'external_parent_integration': []}

    """
    lambda_directories = dict()

    lambda_directories['internal_lambda'] = list(
        set(os.walk(code_dir + '/lambda').__next__()[1]))
    with open(code_dir + '/ext_integration.json') as json_file:
        lambda_parameters = json.load(json_file)

    # TODO identify when lambdas are external?  What is this for?
    lambda_directories['external_lambda'] = list(
        set([lambda_parameter['lambda_name'] for lambda_parameter in lambda_parameters if
             lambda_parameter['lambda_name'] != ""]).difference(
            lambda_directories['internal_lambda']))
    lambda_directories['internal_layers'] = []

    internal_integration = list()
    parent_integration = list()
    for lambda_directory in lambda_directories['internal_lambda']:
        with open(code_dir + '/lambda/' + lambda_directory + '/integration.json') as lambda_json:
            integration_parameters = json.load(lambda_json)
            last_slash = integration_parameters['full_path'].rfind('/')
            integration_parameters['parent'] = integration_parameters['full_path'][:last_slash + 1][:-1]
            integration_parameters['path'] = integration_parameters['full_path'][last_slash + 1:]

            internal_integration.append(integration_parameters['parent'] + '/' + integration_parameters['path'])
            parent_integration.append(integration_parameters['parent'])
    with open(code_dir + '/ext_integration.json') as json_file:
        ext_integration_parameters = json.load(json_file)

        for parameter in ext_integration_parameters:
            last_slash = parameter['full_path'].rfind('/')
            parameter['parent'] = parameter['full_path'][:last_slash + 1][:-1]
            parameter['path'] = parameter['full_path'][last_slash + 1:]

            parent_integration.append(parameter['parent'])
            internal_integration.append(parameter['parent'] + '/' + parameter['path'])

    lambda_directories['external_layers'] = []
    # Parents created in this phase
    lambda_directories['internal_parent_integration'] = list(
        set(internal_integration).intersection(set(parent_integration)))
    # Parent created in before
    lambda_directories['external_parent_integration'] = list(
        set(parent_integration).difference(set(lambda_directories['internal_parent_integration'])))
    lambda_directories['external_parent_integration'].remove("")

    return lambda_directories


def create_data_tf_lambda(ext_lambdas):
    """
    Creates the data resource string for any defined external lambdas.
    :param ext_lambdas: (list)(str) A list of lambda function names to include as data sources.
    :return: (str) The data resource(s) for the provided lambda(s).
    """

    lambda_resource_string = ""
    for ext_lambda in ext_lambdas:
        lambda_resource_string += f"data \"aws_lambda_function\" \"lambda_{ext_lambda}\" {'{'}\n\t" \
                                  f"function_name = \"{ext_lambda}\"\n\t" \
                                  "}\n"

    return lambda_resource_string


def create_data_tf_integration(ext_integration):
    """
    Creates the data resource string for any defined external integrations.
    :param ext_integration: (list)(str) List of parent paths for integrating methods to in the API gateway.
    :return: (str) The data resource(s) for the provided parent path(s).
    """

    integration_resource_string = ""
    for path in ext_integration:
        formatted_path = path.replace('/', '_').replace('-', '_')
        integration_resource_string += f"data \"aws_api_gateway_resource\" \"gateway_resource{formatted_path}\" {'{'}\n\t" \
                                       "rest_api_id = var.rest_api_id\n\t" \
                                       f"path = \"{path}\"\n" \
                                       "}\n"
    return integration_resource_string


def create_data_tf(lambda_directories, terraform_dir, rest_api_name):
    """
    Function creates the data.tf file for referencing the provided {rest_api_name}
    :param lambda_directories: (dict) List of directories derived from the resource_gen function.
    :param terraform_dir: (str) Directory of the terraform code to add this file to.
    :param rest_api_name: (str) The name of api gateway.  Ex. ccd-api
    :return: None
    """
    data_string = (
        'data "aws_api_gateway_resource" "rest_api_root" {\n'
        '\trest_api_id = var.rest_api_id\n'
        '\tpath        = "/"\n'
        '}\n\n'
        'data "aws_region" "current" {}\n\n'
    )


    # TODO identify why we're doing this
    data_string += create_data_tf_lambda(lambda_directories['external_lambda'])
    data_string += create_data_tf_integration(lambda_directories['external_parent_integration'])
    with open(terraform_dir + '/data.tf', 'w') as file:
        file.write(data_string)


def get_parent_resource_id(parent, code_dir):
    obj = resource_gen(code_dir)
    internal_parent_id = set(obj['internal_parent_integration'])
    external_parent_id = set(obj['external_parent_integration'])
    if parent == '':
        return "${data.aws_api_gateway_resource.rest_api_root.id}"
    if parent in internal_parent_id:
        return '${module.' + parent[1:].replace('/', '_').replace('-', '_') + '_resource.resource_id}'
    if parent in external_parent_id:
        return '${data.aws_api_gateway_resource.gateway_resource' + parent.replace('/', '_').replace('-', '_') + '.id}'
