
# Red Hat Advanced Cluster Management

## Install the Advanced Cluster Management Operator

For disconnected environments, update the [mce-repo.yaml](mce-repo.yaml)
manifest, which contains configuration for the MultiCluster Engine repository,
with your mirror registry address.

To manually install `rhacm` in your cluster, navigate to Operators >
OperatorHub, search for Advanced Cluster Management, and install the operator
with the default configuration.

To automate `rhacm` installation, create the
[operator-group.yaml](operator-group.yaml),
[subscription.yaml](subscription.yaml), and
[multiclusterhub.yaml](multiclusterhub.yaml) manifests in the
`open-cluster-management` namespace.

*Installing `rhacm` will automatically install the MultiCluster Engine
Operator.* It will also create the `multiclusterengine` object.

## Configure Central Infrastructure Management

To use the Host Inventory function of `rhacm`, configure and enable Central
Infrastructure Management. This can be performed manually by navigating to
Infrastructure > Host Inventory and clicking on the `Configure host inventory
settings` link on the top right of the page. (See the next paragraph for
disconnected environments.)

For automated or disconnected environments, update the
[agent-service-config.yaml](agent-service-config.yaml) file and apply it to the
cluster.

## References

* [Red Hat Advanced Cluster Management for Kubernetes > Installing](https://docs.redhat.com/en/documentation/red_hat_advanced_cluster_management_for_kubernetes/2.13/html-single/install/index)
* [Red Hat Advanced Cluster Management for Kubernetes > Clusters](https://docs.redhat.com/en/documentation/red_hat_advanced_cluster_management_for_kubernetes/2.13/html-single/clusters/index)
