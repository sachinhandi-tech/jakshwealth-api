import json

MODULE_PATH = '../module_sources'


def get_module_source(module_type):
    """
    Returns the git location of resource to use for this module.
    Ex. The git location of the lambda funciton terraform.
    :param module_type: (str) The name of the module.  Ex. "layer"
    :return: (str) The resource location in git.
    """
    with open(MODULE_PATH + '/sources.json') as json_file:
        resources_dict = json.load(json_file)

    return resources_dict[module_type]
