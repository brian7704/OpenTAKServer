# OpenTAKServer Helm Chart

## Build

1. **Validate chart**
   helm lint helm/

2. **Build chart**
   helm package helm/

## Installation

1. **Update values.yaml**  
   Adjust values to fit your environment.

2. **Install the Chart**  
   helm install opentakserver ./opentakserver-helm

3. **Upgrade the Chart**  
   helm upgrade opentakserver ./opentakserver-helm

4. **Uninstall**  
   helm uninstall opentakserver
