import os
import json
from resource_generation import get_parent_resource_id
from get_module_source import get_module_source


def api_gateway_integration_generation(module_name, methods, path, lambda_name, parent, env, disable_auth=[], need_permission=True, code_dir=None, root_resource_id=None):
    if root_resource_id:
        parent_resource_ref = root_resource_id
    elif parent == '':
        parent_resource_ref = "${data.aws_api_gateway_rest_api.rest_api.root_resource_id}"
    else:
        parent_resource_ref = get_parent_resource_id(parent, code_dir)

    resource_module = f"\nmodule \"{module_name}_resource\" {'{'} \n\t" \
                      f"source = \"{get_module_source('api_gateway_resource')}\"\n\t" \
                      "rest_api_id = \"${data.aws_api_gateway_rest_api.rest_api.id}\"\n\t" \
                      f"root_resource_id = \"{parent_resource_ref}\"\n\t" \
                      f"path = \"{path}\"\n" \
                      "}"

    if lambda_name == "":
        return resource_module

    lambda_permission_module = f"\nmodule \"{module_name}_lambda_permission\" {'{'}\n\t" \
                            f"source = \"{get_module_source('lambda_permission')}\"\n\t" \
                            "rest_api_id = \"${data.aws_api_gateway_rest_api.rest_api.id}\"\n\t" \
                            f"lambda = \"${'{'}module.{lambda_name}.name{'}'}\"\n\t" \
                            "region = \"${var.aws_region}\"\n\t" \
                            "account_id  = \"${data.aws_caller_identity.current.account_id}\"\n" \
                            "}"

    if need_permission == "False":
        lambda_permission_module = ""


    integration_module = str()
    for method in methods:
        # needs to be true, setting it false for testing only
        authorization = "true"
        if method in disable_auth:
            authorization = "false"
        
        if method == 'OPTIONS':
            authorization = "false"

        extra_params = ""

        integration_module += f"\nmodule \"{str.lower(method)}_{module_name}\" {'{'}\n\t" \
                              f"source = \"{get_module_source('api_gateway_integration_jw')}\"\n\t" \
                              "rest_api_id = \"${data.aws_api_gateway_rest_api.rest_api.id}\"\n\t" \
                              f"resource_id = \"${'{'}module.{module_name}_resource.resource_id{'}'}\"\n\t" \
                              f"method = \"{method}\"\n\t" \
                              f"path = \"${'{'}module.{module_name}_resource.path{'}'}\"\n\t" \
                              f"lambda = \"${'{'}module.{lambda_name}.name{'}'}\"\n\t" \
                              "region = \"${var.aws_region}\"\n\t" \
                              "account_id = \"${data.aws_caller_identity.current.account_id}\"\n\t" \
                              f"authorization = \"{authorization}\"\n\t" \
                              f"stage = \"{env}\"\n\t" \
                              f"{extra_params}\n" \
                              "}"

    return resource_module + lambda_permission_module + integration_module


def api_gateway_proxy_integration_generation(base_module_name, methods, path, lambda_name, env, disable_auth=[]):
    """Greedy proxy resource (``{proxy+}``) for secure-data feature subpaths."""
    proxy_module_name = f"{base_module_name}_proxy"
    return api_gateway_integration_generation(
        module_name=proxy_module_name,
        methods=methods,
        path=path,
        lambda_name=lambda_name,
        parent="",
        env=env,
        disable_auth=disable_auth,
        need_permission="False",
        root_resource_id=f"${{module.{base_module_name}_resource.resource_id}}",
    )



def api_integration_gen(env, code_dir, terraform_dir):
    """
    Creates API Gateway resources, methods, and Lambda permissions for JakshWealth endpoints.
    :param env: (str) environment being invoked. Ex. dev.
    :param code_dir: (str) Directory containing the layer sub directory
    :param terraform_dir: (str) Directory of the terraform code to add this file to.
    :return: None
    """
    data_str = "data \"aws_caller_identity\" \"current\" { }\n"

    api_integration_modules = str()

    api_integration_details = list()

    with open(code_dir + '/ext_integration.json') as json_file:

        ext_integration_params = json.load(json_file)

        for parameter in ext_integration_params:
            last_slash = parameter['full_path'].rfind('/')
            parameter['parent'] = parameter['full_path'][:last_slash + 1][:-1]
            parameter['path'] = parameter['full_path'][last_slash + 1:]
            parameter['module_name'] = (parameter['parent'] + '_' + parameter['path'])[1:].replace('/', '_').replace(
                '-', '_').replace('{','').replace('}','')
            parameter['env'] = env
            parameter.pop('layers', None)
            parameter.pop('full_path', None)
            api_integration_details.append(parameter)

    lambda_directories = os.walk(code_dir + '/lambda').__next__()[1]

    for directory in lambda_directories:
        with open(code_dir + '/lambda/' + directory + '/integration.json') as json_file:
            lambda_parameters = json.load(json_file)
            if lambda_parameters.get('lambda_name') == 'jw_authorization':
                continue
            last_slash = lambda_parameters['full_path'].rfind('/')
            lambda_parameters['parent'] = lambda_parameters['full_path'][:last_slash + 1][:-1]
            lambda_parameters['path'] = lambda_parameters['full_path'][last_slash + 1:]
            lambda_parameters['module_name'] = (lambda_parameters['parent'] + '_' + lambda_parameters['path'])[1:].replace('/', '_').replace('-', '_').replace('{','').replace('}','')
            lambda_parameters['env'] = env
            lambda_parameters.pop('layers', None)
            lambda_parameters.pop('full_path', None)
            lambda_parameters.pop('permissions', None)
            allow_subpath = lambda_parameters.pop('allow_subpath', False)
            lambda_parameters['allow_subpath'] = allow_subpath
            api_integration_details.append(lambda_parameters)

    for api_integration in api_integration_details:
        allow_subpath = api_integration.pop('allow_subpath', False)
        # Remove additional parameters unused by api integration
        for parameter in ('additional_policies', 'internet', 'timeout', 'alarm_duration', 'memory', 'additional_security_groups', 'memory_size', 'ephemeral_memory', 'environmental_variables', 'description', 'runtime', 'handler', 'role'):
            if parameter in api_integration:
                del api_integration[parameter]

        module_name = api_integration['module_name']
        api_integration_modules += api_gateway_integration_generation(**api_integration, code_dir=code_dir)
        if allow_subpath:
            api_integration_modules += api_gateway_proxy_integration_generation(
                base_module_name=module_name,
                methods=api_integration['methods'],
                path="{proxy+}",
                lambda_name=api_integration['lambda_name'],
                env=api_integration['env'],
                disable_auth=api_integration.get('disable_auth', []),
            )
    with open(terraform_dir + '/api_integration.tf', 'w') as file:
        file.write(data_str)
        file.write(api_integration_modules)
