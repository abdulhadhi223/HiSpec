
stage('Collect Deployment Metadata') {
    agent { label 'newsc-agent-1' }

    steps {
        script {
            def nmdbBuild = env.DEPLOY_BUILD_NUMBER ?: ''
            def necBuild = env.NEC_DEPLOY_BUILD_NUMBER ?: ''

            def releaseBuildNumber = nmdbBuild.trim()

            if (!releaseBuildNumber) {
                releaseBuildNumber = necBuild.trim()
            }

            if (!releaseBuildNumber) {
                error('No downstream deployment build number found')
            }

            if (!(releaseBuildNumber ==~ '[0-9]+')) {
                error("Invalid deployment build number: ${releaseBuildNumber}")
            }

            echo "Copying metadata from NMDB-DEPLOY #${releaseBuildNumber}"

            copyArtifacts(
                projectName: 'NMDB-DEPLOY',
                selector: specific(releaseBuildNumber),
                filter: 'metadata.html,report.css',
                flatten: true
            )

            sh '''#!/usr/bin/env bash
set -euo pipefail

echo "=== Deployment metadata ==="
ls -lh metadata.html report.css
'''

            archiveArtifacts(
                artifacts: 'metadata.html,report.css',
                fingerprint: true,
                allowEmptyArchive: false
            )
        }
    }
}
