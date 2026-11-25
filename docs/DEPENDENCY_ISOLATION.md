# Application dependency isolation

The application venv is created without system site packages. Python-related
environment overrides are removed when creating the venv, installing packages,
checking dependencies and starting the backend. The startup script retains the
sourced ROS `PYTHONPATH` in `RDK_ROS_PYTHONPATH`; only the fixed system-Python
ROS probe restores it. Other ROS environment variables remain inherited.
`pip check` remains mandatory. Native ROS imports on the physical target remain
unverified with this change.

The physical target's staged venv reported zope-event 5.1.1 requiring
setuptools >=75.8.2 while seeing setuptools 59.6.0. System Python reported no
broken requirements. See UPGRADE_FAILURE_ANALYSIS.md for the evidence and limits.

Local Python 3.10.22 isolated installation and strict `pip check` passed with
cached AMD64 wheels. Native ARM64 dependency installation and the new ROS probe
environment remain to be validated on the physical target.
