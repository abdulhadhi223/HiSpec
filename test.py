stage('Prospector Report') {
    steps {
        sh '''#!/usr/bin/env bash
            set +e

            prospector \
                --output-format json \
                > prospector.json

            PROSPECTOR_RC=$?

            python3 "$RELEASE_PY" prospector-html \
                --input prospector.json \
                --output prospector.html

            echo "Prospector exit code: $PROSPECTOR_RC"

            exit 0
        '''

        archiveArtifacts(
            artifacts: 'prospector.json,prospector.html,report.css',
            fingerprint: true,
            allowEmptyArchive: false
        )
    }
}