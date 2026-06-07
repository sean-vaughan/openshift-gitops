
# Sealed-Secrets Argo Application

This is a `kustomize` application that primarily loads the sealed-secrets helm chart located in the sealed-secrets sub-directory.

In addition to providing the `sealed-secrets` namespace, Kustomize is used in
order allow the sealed secrets pod to run with a specific UID. the
`sealed-secrets-anyuid-scc.yaml` file provides a `ClusterRoleBinding` to the
`system:openshift:scc:anyuid` (a built-in OpenShift `ClusterRole`) for allowing
the sealed-secrets service account to run the sealed-secrets pod with the
hard-coded UID.

# Manual Bootstrap Procedure

1. cd sealed-secrets

2. oc kustomize --enable-helm=true . | oc apply -f -

# KubeSeal Bash Alias

Add to your `~/.bashrc`, `~/.zshrc` or other shell automation as appropriate:

    kubeseal () {
        cat $1 | /usr/local/bin/kubeseal -o yaml --controller-namespace sealed-secrets --controller-name=sealed-secrets > sealed-$1
    }

# KubeSeal Reseal All Secrets

Before attempting to reseal all secrets, verify that the `find` command returns
secret files that *should* be (re)encrypted by reviewing the output:

    find . -name "*-secret.yaml" \! -name "sealed-*.yaml" \
      \! -wholename "./sealed-secrets/sealed-secrets/templates/tls-secret.yaml" \
      -print

If the list of files should be resealed by `kubeseal`, you can run:

    for file in `find . -name "*-secret.yaml" \! -name "sealed-*.yaml" \
      \! -wholename "./sealed-secrets/sealed-secrets/templates/tls-secret.yaml" \
      -print`
    do
      cd $( dirname $file )
      cat $( basename $file ) \
      | /usr/local/bin/kubeseal -o yaml --controller-namespace sealed-secrets \
        --controller-name sealed-secrets \
      > "sealed-$( basename $file )"
      popd
    done
