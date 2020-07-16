#!/usr/bin/env python


import boto3
import time
import os
import sys
import argparse

instancelist = []
instance_ids = []

class backupInstance(object):
   instanceid = ""
   #orig_vol_id@@device_name@@snapshot_vol_id@@new_vol_id
   volume_snapshot_list = []

def validate_instance_count(ec2, cluster_instance_filter):

   response = ec2.describe_instances()

   instancetags = []

   for reservation in response["Reservations"]:
     for instance in reservation["Instances"]:
       instancename = "unknown"
       try: 
         for tags in instance['Tags']:
           if tags["Key"] == 'Name':
             instancename = tags["Value"]

             if cluster_instance_filter in instancename:
               instancetags.append(instancename)
               instancelist.append(instance)
               instance_ids.append(instance["InstanceId"])
       except:
         print "instance has no tags:" + instance["InstanceId"]

   for tag in instancetags:
     print(tag)
 
   print("Please review the instances above to make sure they match what you want to " + args.mode)
   checkresponse = raw_input("Are you sure you want to continue, enter yes or no: ")

   if checkresponse == "no":
     sys.exit()
   elif checkresponse == "yes":

     if len(instancelist) == int(cluster_node_count):
       print "Cluster instance count matches!!"
     else:
       print "Houston, We Have A Problem!!"
       print "The known instance count for this cluster doesn't match our filtered results, exiting"
       sys.exit(1)
   else:
     print "You entered and incorrect value, exiting"
     sys.exit(1)
     

def create_snapshot(ec2, filter, snapshot_name):

    print ("create_snaphot for " + filter + " cluster with snapshot name " + snapshot_name)

    validate_instance_count(ec2, filter)

    for instance in instancelist:
      #print(instance)
      #print(instance["InstanceId"], instancename, instance["KeyName"], instance["State"]["Name"])
      for device in instance["BlockDeviceMappings"]:
        #print(device.get('DeviceName'))
        volume = device.get('Ebs')
        #print(volume.get('VolumeId'))
        volid = volume.get('VolumeId')
 
        response = ec2.describe_volumes(VolumeIds=[volid])

        volzero = response['Volumes'][0]

        az = volzero['AvailabilityZone']
        voltype = volzero['VolumeType']
        encrypted = str(volzero['Encrypted'])
        iops = str(volzero['Iops'])
        size = str(volzero['Size'])
        
        snapshot_desc = instance["InstanceId"] + "_" + az + "_" + voltype + "_" + size + "_" + iops + "_" + encrypted + "_" + volid + "_" + device.get('DeviceName') + "_" + snapshot_name 


        print("Creating Snapshot For " + snapshot_desc)

        snapshot = ec2.create_snapshot(
                              VolumeId=volid, 
                              Description=snapshot_desc,
                      )

        snapid = snapshot['SnapshotId']

        resourcelist = []

        resourcelist.append(snapid)

        tagresponse = ec2.create_tags(
                       Resources=resourcelist, 
                       Tags=
                             [
                               {
                                 'Key': 'Name',
                                 'Value': snapshot_desc
                               }
                              ]
                       )

        timeout = time.time() + 60*40 #40 miutes from now

        time.sleep(10)
 
        while True: 

          response = ec2.describe_snapshots(SnapshotIds=[snapid])

          snapshotzero = response['Snapshots'][0]

          if snapshotzero['State'] == 'completed':
            print("Snapshot completed")
            break
          elif time.time() > timeout:
            print("Snapshot longer than 40 minute, we are going to exit")
            sys.exit(1)
          else:
            print("Sleeping for 10 seconds before checking snaphot status")
            time.sleep(10)
          

def rollback_to_snapshot(ec2, filter, snapshot_filter):
    print ("Ouch!! Rolling Back")

    validate_instance_count(ec2, filter)

    wildcard_filter = "*" + snapshot_filter

    unattach_attach_vols = []

    #get a list of snapshots
    response = ec2.describe_snapshots(
       Filters=
       [
         {
           'Name': 'tag-value',
           'Values': [ wildcard_filter ]
         },
       ]
    )

    snapshots =  response['Snapshots']


    snapshots.sort(key=lambda x: x["Description"])

    #debug crap
    for snapshot in snapshots:
      snap_desc = snapshot['Description']
      print(snap_desc)

    for snapshot in snapshots:
      snapid = snapshot['SnapshotId']
      snap_desc = snapshot['Description']

      print(snapid + " " + snap_desc)

      #i-070b89544028f1367_us-east-1e_gp2_30_100_False_vol-06541fdda22ade765_/dev/sda1_20190821T15:07:21rel-030
      voldata = snap_desc.split("_")
      instanceid = voldata[0]
      az = voldata[1]
      voltype = voldata[2]
      volsize = int(voldata[3])
      iops = int(voldata[4])
      encrypted = False
      if voldata[5] == "True":
        encrypted = True
      volid = voldata[6]
      voldevice = voldata[7]

      print(instanceid + "_" + az + "_" + voltype + "_" + str(volsize) + "_" + str(iops) + "_" + str(encrypted) + "_" + volid + "_" + voldevice)
     
      newvolid = "" 

      #todo to make sure volumes don't already exist
      if voltype == "gp2":
        newvol = ec2.create_volume(
          AvailabilityZone=az,
          Encrypted=encrypted,
          Size=volsize,
          SnapshotId=snapid,
          VolumeType=voltype
        )
        newvolid = newvol['VolumeId'] 
      else:
        newvol = ec2.create_volume(
          AvailabilityZone=az,
          Encrypted=encrypted,
          Size=volsize,
          Iops=iops,
          SnapshotId=snapid,
          VolumeType=voltype
        )
        newvolid = newvol['VolumeId'] 

      #because you might revert from snapshot more than once the initial volume listed in snap_desc
      #could be inaccurate so need to find the current attached volume that aligns to this device
      #to make sure snap_desc is right otherwise our detach volume stuff below will break
      for chkinstance in instancelist:
        #print(instance)
        #print(instance["InstanceId"], instancename, instance["KeyName"], instance["State"]["Name"])
        if instanceid == chkinstance["InstanceId"]:
          for device in chkinstance["BlockDeviceMappings"]:
            if voldevice == device.get('DeviceName'):
               rightvol = device.get('Ebs')
               rightvolid = rightvol.get('VolumeId')
               print("Snapshot Description Before Correction: " + snap_desc)
               snap_desc = instanceid + "_" + az + "_" + voltype + "_" + str(volsize) + "_" + str(iops) + "_" + str(encrypted) + "_" + rightvolid + "_" + voldevice + "_" + snapshot_filter
               print("Snapshot Description After Correction: " + snap_desc)

      vol_descr_old_newvolid = snap_desc + "_" + newvolid

      unattach_attach_vols.append(vol_descr_old_newvolid)

      timeout = time.time() + 60*40 #40 miutes from now

      time.sleep(10)
 
      while True: 

        response = ec2.describe_volumes(VolumeIds=[newvolid])
        #print(response)

        volzero = response['Volumes'][0]

        if volzero['State'] == 'available':
          print("Volume creation completed")
          break
        elif time.time() > timeout:
          print("Volume creation longer than 40 minutee, we are going to exit")
          sys.exit(1)
        else:
          print("Sleeping for 10 seconds before checking volume create status")
          time.sleep(10)


    ec2.stop_instances(InstanceIds=instance_ids)


    print("We are going to sleep for a minute to allow for instances to stop")
    time.sleep(60)

    #todo probably should add a timeout here 
    while True:
 
      response = ec2.describe_instances(InstanceIds=instance_ids)
      #print response

      stopped = "no"
 
      for reservation in response["Reservations"]:
        for instance in reservation["Instances"]:
           
          if instance["State"]["Name"] == "stopped":
            stopped = "yes"
          else:
            stopped = "no"
           
      if stopped == "yes":
        print("All instances stopped")
        break         
      else: 
        print("Going to sleep for another minute to allow for all instances to stop")
        time.sleep(60)
           
    #debug crap
    for vol in unattach_attach_vols:
      print(vol)

    #loop over unattach_attach_vols
    for vol in unattach_attach_vols:
      #i-070b89544028f1367_us-east-1e_gp2_30_100_False_vol-06541fdda22ade765_/dev/sda1_20190821T15:07:21rel-030_vol-06641fdda22ade766
      voldata = vol.split("_")
      instanceid = voldata[0]
      az = voldata[1]
      voltype = voldata[2]
      volsize = int(voldata[3])
      iops = int(voldata[4])
      encrypted = bool(voldata[5])
      volid = voldata[6]
      voldevice = voldata[7]
      newvolid = voldata[9]
      
      print("Detaching volume " + volid + " from " + instanceid)

      response = ec2.detach_volume(
       Device=voldevice,
       InstanceId=instanceid,
       VolumeId=volid
      )       
     
      print("Going to give 30 seconds to allow for volume detach")
      time.sleep(30)

      response = ec2.describe_volumes(VolumeIds=[volid])

      while True:

        volzero = response['Volumes'][0]

        if volzero["State"] == "available":
          print("Detached volume " + volid + " from " + instanceid)
          break
        else:
          print("Going to give another 30 seconds to allow for volume detach")
          time.sleep(30)

      print("All volumes detached from instance " + instanceid)

      print("Attaching volume " + newvolid + " to " + instanceid)

      response = ec2.attach_volume(
       Device=voldevice,
       InstanceId=instanceid,
       VolumeId=newvolid
      )       
     
      print("Going to give 30 seconds to allow for volume attach")
      time.sleep(30)

      response = ec2.describe_volumes(VolumeIds=[newvolid])

      while True:

        volzero = response['Volumes'][0]

        if volzero["State"] == "in-use":
          print("Attached volume " + newvolid + " to " + instanceid)
          break
        else:
          print("Going to give another 30 seconds to allow for volume attach")
          time.sleep(30)

      print("All new volumes attached to instance " + instanceid)


    #loop over instance list and start intances
    ec2.start_instances(InstanceIds=instance_ids)

    print("We are going to sleep for a minute to allow for instances to start")
    time.sleep(60)

    #todo probably should add a timeout here 
    while True:
 
      response = ec2.describe_instances(InstanceIds=instance_ids)
      #print response

      running = "no"
 
      for reservation in response["Reservations"]:
        for instance in reservation["Instances"]:
         
          if instance["State"]["Name"] == "running":
            running = "yes"
          else:
            running = "no"
           
      if running == "yes":
        print("All instances running, rock on!!")
        break         
      else: 
        print("Going to sleep for another minute to allow for all instances to start")
        time.sleep(60)

if __name__ == '__main__':

  #these should come in as an arguments
  #cluster_node_count = 2
  #filter = "z01.dev.ocp.aws.acme.pvt"
  #snapshot_release = "rel-a01pre3u11-188"

  argparser = argparse.ArgumentParser(description='Snapshot EC2 instance volumes or revert to snaphot based on instance name tag filter')
  argparser.add_argument('--cluster_node_count', help='cluster node count')
  argparser.add_argument('--instance_filter', help='instance name tag filter to find instances for snapshot or reversion')
  argparser.add_argument('--snapshot_release', help='align to an ocp release, e.g. rel-a01pre3u11-188')
  argparser.add_argument('--mode', help='snapshot or revert')
  argparser.add_argument('--aws_account', help='aws account dev or prod')
  args = argparser.parse_args()

  if (args.cluster_node_count is None) or (args.instance_filter is None) or (args.snapshot_release is None) or (args.mode is None) or (args.aws_account is None):
    print("Your are missing a required argument, please try again.")
    print('python ec2_snapshot_revert.py --cluster_node_count="2" --instance_filter="z01.dev.ocp.aws.acme.pvt" --snapshot_release="rel-a01pre3u11-188" --mode="snapshot" --aws_account="dev"')
    sys.exit(1)
  else:
    print("Using cluster node count " + args.cluster_node_count)
    print("Using instance filter " + args.instance_filter)
    print("Using snapshot release " + args.snapshot_release)
    print("Using mode " + args.mode)
    print("Using aws_account " + args.aws_account)

  #os.environ["HTTP_PROXY"] = "http://proxy.acme.org:8080"
  #os.environ["HTTPS_PROXY"] = "http://proxy.acme.org:8080"

  snapshot_date = time.strftime('%Y%m%dT%H:%M:%S') 
  snapshot_name = snapshot_date + args.snapshot_release
  print(snapshot_name)

  cluster_node_count = args.cluster_node_count

  if args.aws_account == "dev":
    session = boto3.Session(profile_name='dev')
  elif args.aws_account == "prod":
    session = boto3.Session(profile_name='prod')
  else:
    print("you need to set aws_account for dev or prod")
    sys.exit(1)

  ec2 = session.client('ec2', region_name='us-east-1')
 
  if args.mode == "snapshot":
    create_snapshot(ec2, args.instance_filter, snapshot_name)
  elif args.mode == "revert": 
    print("find snapshot filter string from going int aws console and searching snapshot_release, e.g. 20190821T10:26:59rel-030")
    snapshot_filter = raw_input("Please enter snapshot filter string, e.g. 20190821T10:26:59rel-030 ")
    #terrible validation but better than nothing
    if len(snapshot_filter) == 35:
       print("Rolling back to snapshots with the following filter string: " + snapshot_filter) 
       rollback_to_snapshot(ec2, args.instance_filter, snapshot_filter)
    else:
       print("Your snapshot filter string doesn't appear to be right, exiting") 
       sys.exit(1)
  else:
    print("For mode you need to choose snapshot or revert")
    sys.exit(1) 

