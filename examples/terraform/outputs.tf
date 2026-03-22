output "instance_ids" {
  description = "IDs of the web server instances"
  value       = aws_instance.web[*].id
}

output "instance_public_ips" {
  description = "Public IPs of the web server instances"
  value       = aws_instance.web[*].public_ip
}

output "vpc_id" {
  description = "ID of the VPC"
  value       = module.network.vpc_id
}

output "security_group_id" {
  description = "ID of the web security group"
  value       = aws_security_group.web.id
}
