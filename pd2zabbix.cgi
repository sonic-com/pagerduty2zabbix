#!/usr/bin/perl
use warnings;
use strict;
use CGI;
use Data::Dumper;

my $DEBUG = 1;

my $cgi = CGI->new();

$DEBUG && print STDERR Dumper($cgi);

print $cgi->header();
