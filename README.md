DO NOT USE underscore in your instance_filter or snapshot_release arguments
TODO: error out on the above

#For grabbing snapshot at release point in time

time python -u ec2_snapshot_revert.py --cluster_node_count="15" --instance_filter="t01.dev.ocp.aws.acme.pvt" --snapshot_release="rel-037-t01" --mode="snapshot" | tee rel-037-t01_snapshot.log

#For rolling back to a snapshot

time python -u ec2_snapshot_revert.py --cluster_node_count="15" --instance_filter="t01.dev.ocp.aws.acme.pvt" --snapshot_release="rel-037-t01" --mode="revert" | tee rel-037-t01_revert.log
