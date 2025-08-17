import json
import boto3
import socket
import ipaddress
import logging
import os
from typing import List, Dict, Tuple

# Constants
UPTIMEROBOT_DNS_HOSTNAME = 'ip.uptimerobot.com'
MAX_ENTRIES_PER_SECURITY_GROUP = int(os.environ.get('MAX_ENTRIES_PER_SECURITY_GROUP', '120'))

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
ec2_client = boto3.client('ec2')

def lambda_handler(event, context):
    """Main Lambda handler function"""
    logger.info("Starting UptimeRobot IP address update process")
    
    try:
        # Fetch IP addresses from UptimeRobot DNS
        logger.info("Fetching IP addresses from UptimeRobot DNS")
        ipv4_addresses, ipv6_addresses = fetch_uptimerobot_ips_dns()
        
        logger.info(f"Fetched {len(ipv4_addresses)} IPv4 and {len(ipv6_addresses)} IPv6 addresses")
        
        ipv4_cidrs = []
        ipv6_cidrs = []
        
        # Process IPv4 addresses
        if ipv4_addresses:
            logger.info(f"Processing {len(ipv4_addresses)} IPv4 addresses")
            ipv4_cidrs = consolidate_ips_to_cidrs(ipv4_addresses, 4)
            logger.info(f"Consolidated to {len(ipv4_cidrs)} IPv4 CIDR blocks")
            manage_prefix_list('uptimerobot4', ipv4_cidrs, 'IPv4',
                             'UptimeRobot IPv4 monitoring addresses')
        else:
            logger.warning("No IPv4 addresses found")
        
        # Process IPv6 addresses
        if ipv6_addresses:
            logger.info(f"Processing {len(ipv6_addresses)} IPv6 addresses")
            ipv6_cidrs = consolidate_ips_to_cidrs(ipv6_addresses, 6)
            logger.info(f"Consolidated to {len(ipv6_cidrs)} IPv6 CIDR blocks")
            manage_prefix_list('uptimerobot6', ipv6_cidrs, 'IPv6',
                             'UptimeRobot IPv6 monitoring addresses')
        else:
            logger.warning("No IPv6 addresses found")
        
        logger.info("Successfully completed UptimeRobot IP address update")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Successfully updated UptimeRobot prefix lists',
                'ipv4_cidrs': len(ipv4_cidrs),
                'ipv6_cidrs': len(ipv6_cidrs),
                'total_ipv4_addresses': len(ipv4_addresses),
                'total_ipv6_addresses': len(ipv6_addresses)
            })
        }
        
    except Exception as e:
        error_msg = f"Failed to update UptimeRobot prefix lists: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': error_msg})
        }

def fetch_uptimerobot_ips_dns() -> Tuple[List[str], List[str]]:
    """Fetch IP addresses from UptimeRobot via DNS A/AAAA records"""
    logger.info(f"Querying DNS records for {UPTIMEROBOT_DNS_HOSTNAME}")
    
    ipv4_addresses = []
    ipv6_addresses = []
    
    try:
        # Get all address info (both IPv4 and IPv6)
        addr_info = socket.getaddrinfo(UPTIMEROBOT_DNS_HOSTNAME, None)
        
        for family, type_, proto, canonname, sockaddr in addr_info:
            ip = sockaddr[0]  # Extract IP address from sockaddr tuple
            
            try:
                ip_obj = ipaddress.ip_address(ip)
                if isinstance(ip_obj, ipaddress.IPv4Address):
                    if ip not in ipv4_addresses:  # Avoid duplicates
                        ipv4_addresses.append(ip)
                        logger.debug(f"Found IPv4: {ip}")
                elif isinstance(ip_obj, ipaddress.IPv6Address):
                    if ip not in ipv6_addresses:  # Avoid duplicates
                        ipv6_addresses.append(ip)
                        logger.debug(f"Found IPv6: {ip}")
            except ValueError:
                logger.warning(f"Invalid IP address from DNS: {ip}")
                continue
        
        logger.info(f"DNS query returned {len(ipv4_addresses)} IPv4 and {len(ipv6_addresses)} IPv6 addresses")
        
        if not ipv4_addresses and not ipv6_addresses:
            raise Exception("No IP addresses found in DNS response")
            
        return ipv4_addresses, ipv6_addresses
        
    except socket.gaierror as e:
        error_msg = f"DNS resolution failed for {UPTIMEROBOT_DNS_HOSTNAME}: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)
    except Exception as e:
        logger.error(f"Error fetching IPs from DNS: {str(e)}")
        raise

def consolidate_ips_to_cidrs(ips: List[str], ip_version: int) -> List[str]:
    """Consolidate individual IPs into CIDR blocks using ipaddress.collapse_addresses"""
    logger.info(f"Consolidating {len(ips)} IPv{ip_version} addresses")
    
    # Convert IPs to address objects
    addresses = []
    for ip in ips:
        try:
            if ip_version == 4:
                addresses.append(ipaddress.IPv4Address(ip))
            else:
                addresses.append(ipaddress.IPv6Address(ip))
        except ValueError:
            
            logger.warning(f"Failed to parse IP address: {ip}")
            continue
    
    # Use ipaddress.collapse_addresses to consolidate into optimal CIDR blocks
    consolidated_networks = list(ipaddress.collapse_addresses(addresses))
    
    result = [str(network) for network in consolidated_networks]
    
    
    logger.info(f"Consolidated {len(ips)} IPv{ip_version} addresses into {len(result)} CIDR blocks")
    if len(result) < len(ips):
        
        logger.info(f"Consolidation saved {len(ips) - len(result)} prefix list entries")
    
    return result

def manage_prefix_list(name: str, cidrs: List[str], address_family: str, description: str):
    """Create or update a managed prefix list"""
    
    logger.info(f"Managing prefix list: {name} ({address_family})")
    
    try:
        existing_pl = find_prefix_list(name)
        
        if existing_pl:
            logger.info(f"Found existing prefix list {name} (ID: {existing_pl['PrefixListId']})")
            update_prefix_list(existing_pl['PrefixListId'], cidrs)
            
            logger.info(f"Updated prefix list {name} with {len(cidrs)} entries")
        else:
            
            logger.info(f"Creating new prefix list: {name}")
            pl_id = create_prefix_list(name, cidrs, address_family, description)
            
            logger.info(f"Created prefix list {name} (ID: {pl_id}) with {len(cidrs)} entries")
            
    except Exception as e:
        
        logger.error(f"Error managing prefix list {name}: {str(e)}", exc_info=True)
        raise

def find_prefix_list(name: str) -> Dict:
    """Find existing prefix list by name"""
    try:
        logger.debug(f"Searching for prefix list: {name}")
        response = ec2_client.describe_managed_prefix_lists()
        
        for pl in response['PrefixLists']:
            if pl['PrefixListName'] == name:
                logger.debug(f"Found prefix list {name}: {pl['PrefixListId']}")
                return pl
        
        logger.debug(f"Prefix list {name} not found")
        return None
        
    except Exception as e:
        logger.error(f"Error finding prefix list {name}: {str(e)}")
        return None

def create_prefix_list(name: str, cidrs: List[str], address_family: str, description: str):
    """Create a new managed prefix list"""
    logger.info(f"Creating prefix list {name} with {len(cidrs)} entries")
    
    # AWS create_managed_prefix_list allows max 100 entries initially
    initial_entries = cidrs[:100]
    remaining_entries = cidrs[100:]
    
    entries = [{'Cidr': cidr, 'Description': f'UptimeRobot monitoring address returned from {UPTIMEROBOT_DNS_HOSTNAME}'} 
              for cidr in initial_entries]
    
    response = ec2_client.create_managed_prefix_list(
        PrefixListName=name,
        Entries=entries,
        MaxEntries=min(len(cidrs) + 20, MAX_ENTRIES_PER_SECURITY_GROUP),
        AddressFamily=address_family,
        TagSpecifications=[{
            'ResourceType': 'prefix-list',
            'Tags': [
                {'Key': 'Name', 'Value': name},
                {'Key': 'SourceUrl', 'Value': UPTIMEROBOT_DNS_HOSTNAME},
                {'Key': 'ManagedBy', 'Value': 'Lambda'}
            ]
        }]
    )
    
    pl_id = response['PrefixList']['PrefixListId']
    logger.info(f"Successfully created prefix list {name} with ID: {pl_id}")
    
    # Add remaining entries if any
    if remaining_entries:
        import time
        logger.info(f"Adding {len(remaining_entries)} additional entries")
        # Wait for prefix list to be available, only takes a few seconds
        # but we need to ensure it's ready before modifying
        for _ in range(30):
            try:
                pl_status = ec2_client.describe_managed_prefix_lists(PrefixListIds=[pl_id])['PrefixLists'][0]
                if 'complete' in pl_status['State']:
                    break
                time.sleep(2)
            except:
                time.sleep(2)
        
        current_version = response['PrefixList']['Version']
        ec2_client.modify_managed_prefix_list(
            PrefixListId=pl_id,
            CurrentVersion=current_version,
            AddEntries=[{'Cidr': cidr, 'Description': f'UptimeRobot monitoring address returned from {UPTIMEROBOT_DNS_HOSTNAME}'} 
                       for cidr in remaining_entries]
        )
    
    return pl_id

def update_prefix_list(prefix_list_id: str, cidrs: List[str]):
    """Update existing managed prefix list"""
    logger.info(f"Updating prefix list {prefix_list_id}")
    
    # Get current entries with pagination
    current_cidrs = set()
    next_token = None
    while True:
        params = {'PrefixListId': prefix_list_id}
        if next_token:
            params['NextToken'] = next_token
        
        current_response = ec2_client.get_managed_prefix_list_entries(**params)
        current_cidrs.update(entry['Cidr'] for entry in current_response['Entries'])
        
        next_token = current_response.get('NextToken')
        if not next_token:
            break
    new_cidrs = set(cidrs)
    
    to_add = new_cidrs - current_cidrs
    to_remove = current_cidrs - new_cidrs
    
    logger.info(f"Current entries: {len(current_cidrs)}, New entries: {len(new_cidrs)}")
    logger.info(f"To add: {len(to_add)}, To remove: {len(to_remove)}")
    
    if not to_add and not to_remove:
        logger.info("No changes needed for prefix list")
        return
    
    if to_add:
        logger.info(f"Adding entries: {list(to_add)}")
    if to_remove:
        logger.info(f"Removing entries: {list(to_remove)}")
    
    # Get current version
    pl_response = ec2_client.describe_managed_prefix_lists(
        PrefixListIds=[prefix_list_id]
    )
    current_version = pl_response['PrefixLists'][0]['Version']
    logger.info(f"Current prefix list version: {current_version}")
    
    # Modify prefix list
    modify_params = {
        'PrefixListId': prefix_list_id,
        'CurrentVersion': current_version
    }
    
    if to_remove:
        modify_params['RemoveEntries'] = [{'Cidr': cidr} for cidr in to_remove]

    if to_add:
        modify_params['AddEntries'] = [
            {'Cidr': cidr, 'Description': f'UptimeRobot monitoring address returned from {UPTIMEROBOT_DNS_HOSTNAME}'}
            for cidr in to_add
        ]
    
    response = ec2_client.modify_managed_prefix_list(**modify_params)
    logger.info(f"Prefix list modification initiated. New version: {response.get('PrefixList', {}).get('Version', 'unknown')}")
    logger.info(f"Successfully updated prefix list {prefix_list_id}")
